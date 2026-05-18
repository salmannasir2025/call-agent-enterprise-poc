"""
audio_router.py — Sounddevice stream initialization, buffer handling,
                  and virtual audio cable device mapping.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import contextmanager
from typing import Final, Generator, Optional

import sounddevice as sd

from config import AudioConfig

log: Final = logging.getLogger("audio_router")

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------
AudioQueue = asyncio.Queue[Optional[bytes]]   # None == sentinel / EOF


# ---------------------------------------------------------------------------
# Device enumeration helper
# ---------------------------------------------------------------------------
def list_audio_devices() -> None:
    """Log all available Sounddevice host devices for debugging / device mapping."""
    devices = sd.query_devices()
    log.info("Available audio devices (%d total):", len(devices))
    for i, info in enumerate(devices):
        log.info(
            "  [%2d] %s | in=%d out=%d | rate=%.0f",
            i,
            info["name"],
            info["max_input_channels"],
            info["max_output_channels"],
            info["default_samplerate"],
        )


def resolve_device_index(
    index: int,
    direction: str,           # "input" | "output"
) -> Optional[int]:
    """
    Return the device index to pass to Sounddevice.
    -1 sentinel → None (use system default).
    """
    if index < 0:
        return None
    try:
        info = sd.query_devices(index)
        key = "max_input_channels" if direction == "input" else "max_output_channels"
        if info[key] < 1:
            raise ValueError(
                f"Device {index} ({info['name']}) has no {direction} channels."
            )
        log.info("Using %s device [%d]: %s", direction, index, info["name"])
        return index
    except Exception as exc:
        raise RuntimeError(f"Invalid {direction} device index {index}: {exc}") from exc


# ---------------------------------------------------------------------------
# Input router — microphone / virtual cable → asyncio queue
# ---------------------------------------------------------------------------
class AudioInputRouter:
    """
    Opens a Sounddevice input stream and feeds raw PCM chunks into an asyncio Queue.
    """

    def __init__(
        self,
        cfg: AudioConfig,
        queue: AudioQueue,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._cfg = cfg
        self._queue = queue
        self._loop = loop
        self._stream: Optional[sd.RawInputStream] = None
        self._active = threading.Event()

    def _callback(self, indata, frames, time, status):
        if status:
            log.warning("Input stream status: %s", status)
        if indata and self._active.is_set():
            chunk = bytes(indata)
            self._loop.call_soon_threadsafe(self._queue.put_nowait, chunk)

    def start(self) -> None:
        device_index = resolve_device_index(self._cfg.input_device_index, "input")
        self._stream = sd.RawInputStream(
            samplerate=self._cfg.input_sample_rate,
            blocksize=self._cfg.input_chunk_frames,
            device=device_index,
            channels=self._cfg.input_channels,
            dtype='int16',
            callback=self._callback
        )
        self._active.set()
        self._stream.start()
        log.info(
            "AudioInputRouter started | rate=%d | chunk=%d frames",
            self._cfg.input_sample_rate,
            self._cfg.input_chunk_frames,
        )

    def stop(self) -> None:
        self._active.clear()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                log.warning("Error closing input stream: %s", exc)
            self._stream = None
        # Push sentinel so downstream consumers can exit cleanly
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        except RuntimeError:
            pass  # event loop already closed
        log.info("AudioInputRouter stopped.")


# ---------------------------------------------------------------------------
# Output router — asyncio queue → speaker / virtual cable
# ---------------------------------------------------------------------------
class AudioOutputRouter:
    """
    Reads raw PCM bytes from an asyncio Queue and writes them to a Sounddevice
    output stream.

    Supports instant hardware-level interrupts via trigger_interrupt():
    sets an abort flag that drops all pending PCM writes and flushes the
    sounddevice internal ring buffer by cycling stop/start.
    """

    def __init__(self, cfg: AudioConfig) -> None:
        self._cfg = cfg
        self._stream: Optional[sd.RawOutputStream] = None
        self._abort_playback = threading.Event()  # Set = muted, Clear = active

    def start(self) -> None:
        self._abort_playback.clear()
        device_index = resolve_device_index(self._cfg.output_device_index, "output")
        self._stream = sd.RawOutputStream(
            samplerate=self._cfg.output_sample_rate,
            blocksize=self._cfg.output_chunk_frames,
            device=device_index,
            channels=self._cfg.output_channels,
            dtype='int16'
        )
        self._stream.start()
        log.info(
            "AudioOutputRouter started | rate=%d | chunk=%d frames",
            self._cfg.output_sample_rate,
            self._cfg.output_chunk_frames,
        )

    def write(self, pcm: bytes) -> None:
        """Write PCM chunk — silently dropped if abort flag is set."""
        if self._abort_playback.is_set():
            return  # Interrupt active — discard audio
        if self._stream is not None and pcm:
            try:
                self._stream.write(pcm)
            except Exception as exc:
                log.error("Audio write error: %s", exc)

    def trigger_interrupt(self) -> None:
        """Instantly mutes AI audio and flushes the hardware ring buffer.

        Sets the abort flag to drop all incoming PCM writes, then cycles
        the stream stop/start to purge any audio already queued in the
        sounddevice internal buffer before this call.
        """
        self._abort_playback.set()
        if self._stream is not None:
            try:
                self._stream.stop()   # Discards buffered audio
                self._stream.start()  # Reopens stream in silence
            except Exception as exc:
                log.warning("Stream flush error during interrupt: %s", exc)
        log.info("AudioOutputRouter: hardware interrupt triggered, buffer flushed.")

    def reset_interrupt(self) -> None:
        """Re-enables PCM writes after a hot interrupt."""
        self._abort_playback.clear()
        log.info("AudioOutputRouter: playback re-enabled.")

    def stop(self) -> None:
        self._abort_playback.set()  # Prevent writes during teardown
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                log.warning("Error closing output stream: %s", exc)
            self._stream = None
        log.info("AudioOutputRouter stopped.")


# ---------------------------------------------------------------------------
# Context-manager convenience wrappers
# ---------------------------------------------------------------------------
@contextmanager
def managed_input_router(
    cfg: AudioConfig,
    queue: AudioQueue,
    loop: asyncio.AbstractEventLoop,
) -> Generator[AudioInputRouter, None, None]:
    router = AudioInputRouter(cfg, queue, loop)
    try:
        router.start()
        yield router
    finally:
        router.stop()


@contextmanager
def managed_output_router(cfg: AudioConfig) -> Generator[AudioOutputRouter, None, None]:
    router = AudioOutputRouter(cfg)
    try:
        router.start()
        yield router
    finally:
        router.stop()
