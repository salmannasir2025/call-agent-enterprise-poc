"""
pipeline.py — Asyncio core loop orchestrating STT → LLM → TTS.

Stage topology (all connected via asyncio.Queue):

  [AudioInputRouter]
        │  raw PCM bytes
        ▼
  [ STT Worker ]  ──── Deepgram streaming WebSocket
        │  finalized transcript str
        ▼
  [ LLM Worker ]  ──── Gemini generate_content (streaming)
        │  text chunks
        ▼
  [ TTS Worker ]  ──── Deepgram TTS REST streaming
        │  raw PCM bytes
        ▼
  [AudioOutputRouter]
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import json
import struct
import os
from datetime import datetime
from typing import Final, Optional, AsyncIterator

import aiohttp
import google.generativeai as genai
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)

from config import Config
from audio_router import AudioOutputRouter, AudioQueue

log: Final = logging.getLogger("pipeline")

# Sentinel value — signals shutdown to downstream queue consumers
_SHUTDOWN: Final[None] = None


# ---------------------------------------------------------------------------
# Stage 1 — STT  (Deepgram streaming WebSocket)
# ---------------------------------------------------------------------------
class STTWorker:
    """
    Consumes raw PCM from `audio_queue`, forwards to Deepgram Live STT,
    and pushes final transcripts onto `transcript_queue`.
    """

    def __init__(
        self,
        cfg: Config,
        audio_queue: AudioQueue,
        transcript_queue: asyncio.Queue[Optional[str]],
    ) -> None:
        self._cfg = cfg
        self._audio_q = audio_queue
        self._transcript_q = transcript_queue
        self._dg_client = DeepgramClient(
            cfg.keys.deepgram,
            DeepgramClientOptions(options={"keepalive": "true"}),
        )

    async def run(self) -> None:
        log.info("STTWorker starting…")
        live_opts = LiveOptions(
            model=self._cfg.stt.model,
            language=self._cfg.stt.language,
            punctuate=self._cfg.stt.punctuate,
            interim_results=self._cfg.stt.interim_results,
            utterance_end_ms=str(self._cfg.stt.utterance_end_ms),
            endpointing=str(self._cfg.stt.endpointing),
            encoding="linear16",
            channels=self._cfg.audio.input_channels,
            sample_rate=self._cfg.audio.input_sample_rate,
        )

        try:
            conn = self._dg_client.listen.asyncwebsocket.v("1")
            
            conn.on(
                LiveTranscriptionEvents.Transcript,
                self._on_transcript,
            )
            conn.on(
                LiveTranscriptionEvents.Error,
                self._on_error,
            )

            if not await conn.start(live_opts):
                log.error("STTWorker: Deepgram WebSocket failed to connect.")
                return

            log.info("Deepgram WebSocket connected.")

            # Feed audio chunks to Deepgram
            while True:
                chunk = await self._audio_q.get()
                if chunk is _SHUTDOWN:
                    log.info("STTWorker received shutdown sentinel.")
                    break
                try:
                    await conn.send(chunk)
                except Exception as exc:
                    log.error("STT send error: %s — dropping chunk.", exc)
                finally:
                    self._audio_q.task_done()

            await conn.finish()

        except Exception as exc:
            log.exception("STTWorker fatal error: %s", exc)
        finally:
            await self._transcript_q.put(_SHUTDOWN)
            log.info("STTWorker stopped.")

    # ------------------------------------------------------------------
    # Deepgram event handlers
    # ------------------------------------------------------------------
    async def _on_transcript(self, *args, **kwargs) -> None:
        result = kwargs.get("result") or (args[1] if len(args) > 1 else None)
        if result is None:
            return
        try:
            alt = result.channel.alternatives[0]
            text: str = alt.transcript.strip()
            if not text:
                return
            is_final: bool = result.is_final
            if is_final:
                log.debug("STT final: %r", text)
                try:
                    self._transcript_q.put_nowait(text)
                except asyncio.QueueFull:
                    log.warning("Transcript queue full — dropping: %r", text)
        except (AttributeError, IndexError) as exc:
            log.warning("Malformed transcript result: %s", exc)

    async def _on_error(self, *args, **kwargs) -> None:
        error = kwargs.get("error") or (args[1] if len(args) > 1 else None)
        log.error("Deepgram STT error event: %s", error)


# ---------------------------------------------------------------------------
# Stage 2 — LLM  (Gemini streaming)
# ---------------------------------------------------------------------------
class LLMWorker:
    """
    Consumes transcripts from `transcript_queue`, streams responses from
    Gemini Flash-Lite, and pushes text chunks onto `tts_text_queue`.
    """

    def __init__(
        self,
        cfg: Config,
        transcript_queue: asyncio.Queue[Optional[str]],
        tts_text_queue: asyncio.Queue[Optional[str]],
    ) -> None:
        self._cfg = cfg
        self._transcript_q = transcript_queue
        self._tts_text_q = tts_text_queue

        genai.configure(api_key=cfg.keys.gemini)
        self._model = genai.GenerativeModel(
            model_name=cfg.llm.model,
            system_instruction=cfg.llm.system_prompt,
            generation_config=genai.GenerationConfig(
                temperature=cfg.llm.temperature,
                max_output_tokens=cfg.llm.max_tokens,
            ),
        )
        self._chat = self._model.start_chat(history=[])

        # Setup Conversation Log
        os.makedirs("output", exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._log_file = f"output/call_{timestamp}.txt"
        with open(self._log_file, "w", encoding="utf-8") as f:
            f.write(f"Call Agent Conversation Log - {timestamp}\n")
            f.write("==================================================\n\n")

    async def run(self) -> None:
        log.info("LLMWorker starting…")
        try:
            while True:
                transcript = await self._transcript_q.get()
                if transcript is _SHUTDOWN:
                    log.info("LLMWorker received shutdown sentinel.")
                    break

                log.info("LLM ← %r", transcript)

                # Deferred disk write — never block the async loop on file I/O
                loop = asyncio.get_running_loop()
                loop.run_in_executor(
                    None,
                    self._log_to_disk,
                    f"Caller: {transcript}\n",
                )

                try:
                    await self._stream_response(transcript)
                except Exception as exc:
                    log.error("LLM generation error: %s", exc)
                finally:
                    self._transcript_q.task_done()

        finally:
            await self._tts_text_q.put(_SHUTDOWN)
            log.info("LLMWorker stopped.")

    async def _stream_response(self, user_text: str) -> None:
        """Stream Gemini response without blocking the asyncio event loop.

        FIX: The original design offloaded only the iterator creation to a thread
        pool, then consumed chunks on the main thread — causing blocking network I/O
        on every chunk. Now the ENTIRE blocking iteration runs inside run_in_executor,
        collecting all chunks before handing control back to the async loop.
        """
        loop = asyncio.get_running_loop()

        def _blocking_collect() -> list[str]:
            """Runs fully inside thread pool — blocks there, never on the event loop."""
            response = self._chat.send_message(user_text, stream=True)
            chunks: list[str] = []
            for chunk in response:
                text = chunk.text if hasattr(chunk, "text") else ""
                if text:
                    chunks.append(text)
            return chunks

        try:
            text_chunks = await loop.run_in_executor(None, _blocking_collect)
        except Exception as exc:
            log.error("LLM executor error: %s", exc)
            return

        full_response = ""
        for text in text_chunks:
            full_response += text
            log.debug("LLM chunk: %r", text)
            await self._tts_text_q.put(text)
                
        # Deferred disk write — offloaded to thread pool, never touches event loop
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None,
            self._log_to_disk,
            f"Agent: {full_response.strip()}\n\n",
        )

        # Sentence boundary marker — TTS worker flushes on this
        await self._tts_text_q.put("\n")

    def _log_to_disk(self, content: str) -> None:
        """Isolated synchronous disk writer — always called from thread pool only."""
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {content}")
        except IOError as exc:
            log.error("Disk log write failed: %s", exc)


# ---------------------------------------------------------------------------
# Stage 3 — TTS  (Deepgram TTS REST streaming)
# ---------------------------------------------------------------------------
class TTSWorker:
    """
    Consumes text chunks from `tts_text_queue`, synthesizes PCM audio 
    via Deepgram Speak API using a single, warmed, persistent session connection.
    """
    def __init__(
        self,
        cfg: Config,
        tts_text_queue: asyncio.Queue[Optional[str]],
        output_router: AudioOutputRouter,
    ) -> None:
        self._cfg = cfg
        self._tts_text_q = tts_text_queue
        self._output = output_router

    async def run(self) -> None:
        log.info("TTSWorker: Initializing persistent HTTP session pool...")
        
        # Open a single shared connection context for the life of the pipeline
        async with aiohttp.ClientSession() as session:
            buffer = ""
            while True:
                text = await self._tts_text_q.get()
                if text is _SHUTDOWN:
                    self._tts_text_q.task_done()
                    # Flush remaining buffer
                    if buffer.strip():
                        try:
                            await self._synthesize_and_stream(session, buffer.strip())
                        except Exception as exc:
                            log.error("TTS Synthesis execution dropped on shutdown: %s", exc)
                    break

                if text is None:
                    self._tts_text_q.task_done()
                    continue

                buffer += text
                self._tts_text_q.task_done()

                # Low-latency sentence boundary splitting
                if any(p in text for p in (".", "?", "!", "\n")):
                    sentences = []
                    current = ""
                    for char in buffer:
                        current += char
                        if char in (".", "?", "!", "\n"):
                            sentences.append(current)
                            current = ""
                    
                    buffer = current
                    
                    for sentence in sentences:
                        clean_sentence = sentence.strip()
                        if clean_sentence:
                            try:
                                await self._synthesize_and_stream(session, clean_sentence)
                            except Exception as exc:
                                log.error("TTS Synthesis execution dropped: %s", exc)

        log.info("TTSWorker: Session pool successfully drained and terminated.")

    async def _synthesize_and_stream(self, session: aiohttp.ClientSession, text: str) -> None:
        log.info("TTS Synthesis ← %r", text)
        url = f"https://api.deepgram.com/v1/speak?model={self._cfg.tts.model}&encoding=linear16&sample_rate=24000"
        headers = {
            "Authorization": f"Token {self._cfg.keys.deepgram}",
            "Content-Type": "application/json",
        }
        payload = {"text": text}

        # Echo Cancellation: Signal that AI is actively speaking
        self._output.is_playing.set()

        try:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status != 200:
                    log.error("Deepgram TTS returned non-200 state: %d", response.status)
                    return

                # Push incoming streaming audio chunks straight to hardware with zero disk-write lag
                async for chunk, _ in response.content.iter_chunks():
                    if self._output._abort_playback.is_set():
                        log.info("Hot Interrupt detected: Aborting downstream audio playback loop.")
                        break
                    self._output.write(chunk)
        finally:
            # Echo Cancellation: Clear the playing flag after buffer drains (400ms padding)
            asyncio.create_task(self._clear_playing_flag_delayed())

    async def _clear_playing_flag_delayed(self) -> None:
        await asyncio.sleep(0.4)
        self._output.is_playing.clear()


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------
class VoicePipeline:
    """
    Owns all three workers and their inter-stage queues.
    Call `run()` from the asyncio event loop.
    """

    def __init__(self, cfg: Config, output_router: AudioOutputRouter) -> None:
        self._cfg = cfg
        self._output = output_router

        p = cfg.pipeline
        self.audio_queue: AudioQueue = asyncio.Queue(maxsize=p.stt_queue_maxsize)
        self._transcript_queue: asyncio.Queue[Optional[str]] = asyncio.Queue(
            maxsize=p.llm_queue_maxsize
        )
        self._tts_text_queue: asyncio.Queue[Optional[str]] = asyncio.Queue(
            maxsize=p.tts_queue_maxsize
        )

        self._stt = STTWorker(cfg, self.audio_queue, self._transcript_queue)
        self._llm = LLMWorker(cfg, self._transcript_queue, self._tts_text_queue)
        self._tts = TTSWorker(cfg, self._tts_text_queue, output_router)

        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        log.info("VoicePipeline starting…")
        self._tasks = [
            asyncio.create_task(self._stt.run(), name="stt"),
            asyncio.create_task(self._llm.run(), name="llm"),
            asyncio.create_task(self._tts.run(), name="tts"),
        ]

    async def stop(self) -> None:
        """Graceful shutdown: inject sentinel, then wait for drain."""
        log.info("VoicePipeline shutting down…")
        # Signal the head of the pipeline; sentinels propagate downstream
        try:
            self.audio_queue.put_nowait(_SHUTDOWN)
        except asyncio.QueueFull:
            pass

        timeout = self._cfg.pipeline.shutdown_timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            log.warning("Pipeline did not drain in %.1fs — cancelling tasks.", timeout)
            for t in self._tasks:
                t.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
        log.info("VoicePipeline stopped.")

    def hot_interrupt_pipeline(self) -> None:
        """Instantly silences AI output and purges all pending queues.

        Call this when the human operator needs to take control of the call.
        Execution flow:
          1. Hardware audio output is muted and its internal buffer flushed.
          2. The transcript queue is purged — no queued user speech will fire LLM.
          3. The TTS text queue is purged — no queued AI script will be synthesized.
        The pipeline remains alive; it simply resumes listening cleanly.
        """
        log.info("HOT INTERRUPT: Flushing audio and purging pipeline queues.")

        # Step 1: Kill hardware audio output immediately
        self._output.trigger_interrupt()

        # Step 2: Drain transcript queue (pending STT results)
        purged = 0
        while not self._transcript_queue.empty():
            try:
                self._transcript_queue.get_nowait()
                self._transcript_queue.task_done()
                purged += 1
            except (asyncio.QueueEmpty, ValueError):
                break

        # Step 3: Drain TTS text queue (pending AI script)
        while not self._tts_text_queue.empty():
            try:
                self._tts_text_queue.get_nowait()
                self._tts_text_queue.task_done()
                purged += 1
            except (asyncio.QueueEmpty, ValueError):
                break

        log.info("HOT INTERRUPT: %d queued items purged. Pipeline reset for human takeover.", purged)

    def reset_interrupt(self) -> None:
        """Re-enables AI audio output after a hot interrupt."""
        self._output.reset_interrupt()
        log.info("Audio output re-enabled. AI pipeline resumed.")
