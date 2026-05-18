"""
main.py — Graceful initialization, SIGINT/SIGTERM handlers, and clean shutdown.
Entry point for the real-time voice-to-voice pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Final

from config import load_config
from audio_router import (
    managed_input_router,
    managed_output_router,
    list_audio_devices,
)
from pipeline import VoicePipeline

log: Final = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Shutdown coordinator
# ---------------------------------------------------------------------------
class _ShutdownController:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def request_shutdown(self, signame: str = "manual") -> None:
        if not self._event.is_set():
            log.info("Shutdown requested via %s.", signame)
            self._event.set()

    async def wait(self) -> None:
        await self._event.wait()


# ---------------------------------------------------------------------------
# Core async entrypoint
# ---------------------------------------------------------------------------
async def _amain() -> int:
    cfg = load_config()

    # Print device list on first run to help configure AUDIO_INPUT/OUTPUT_DEVICE
    list_audio_devices()

    shutdown = _ShutdownController()
    loop = asyncio.get_running_loop()

    # Register OS signal handlers inside the running loop
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            lambda s=sig: shutdown.request_shutdown(signal.Signals(s).name),
        )

    log.info("Initializing audio I/O…")

    with managed_output_router(cfg.audio) as out_router:
        pipeline = VoicePipeline(cfg, out_router)

        with managed_input_router(cfg.audio, pipeline.audio_queue, loop) as _in_router:
            await pipeline.start()
            log.info("Pipeline live. Speak into your microphone. Ctrl+C to quit.")

            try:
                await shutdown.wait()
            finally:
                await pipeline.stop()

    log.info("Shutdown complete.")
    return 0


# ---------------------------------------------------------------------------
# Synchronous wrapper with top-level exception guard
# ---------------------------------------------------------------------------
def main() -> None:
    exit_code = 1
    try:
        exit_code = asyncio.run(_amain())
    except KeyboardInterrupt:
        # asyncio.run() may re-raise SIGINT as KeyboardInterrupt on some
        # platforms even after we handle it — catch silently.
        log.info("Interrupted by keyboard.")
        exit_code = 0
    except EnvironmentError as exc:
        # Missing API keys or bad config — already logged in config.py
        log.critical("Startup failed: %s", exc)
        exit_code = 2
    except Exception as exc:
        log.exception("Unhandled exception in main: %s", exc)
        exit_code = 1
    finally:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
