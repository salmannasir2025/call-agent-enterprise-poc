"""
config.py — Environment parsing, validation, and runtime constants.
All secrets sourced exclusively from environment variables.
"""

from __future__ import annotations

import os
import sys
import logging
from dataclasses import dataclass, field
from typing import Final

# ---------------------------------------------------------------------------
# Logging bootstrap (before any other module imports this file)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stderr,
)
log: Final = logging.getLogger("config")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _require(key: str) -> str:
    """Raise EnvironmentError if key is absent or empty."""
    value = os.getenv(key, "").strip()
    if not value:
        log.critical("Required environment variable '%s' is not set.", key)
        raise EnvironmentError(f"Missing required env var: {key}")
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class APIKeys:
    deepgram: str = field(default_factory=lambda: _require("DEEPGRAM_API_KEY"))
    gemini: str   = field(default_factory=lambda: _require("GEMINI_API_KEY"))


# ---------------------------------------------------------------------------
# Audio constants
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AudioConfig:
    # Input stream (microphone / virtual cable)
    input_sample_rate: int  = 16_000
    input_channels: int     = 1
    input_chunk_frames: int = 1_024          # ~64 ms @ 16 kHz
    input_format: int       = 8              # pyaudio.paInt16 == 8

    # Output stream (speaker / virtual cable)
    output_sample_rate: int  = 24_000
    output_channels: int     = 1
    output_chunk_frames: int = 2_048

    # Device indices — override via env vars; -1 = system default
    input_device_index: int  = field(
        default_factory=lambda: int(_optional("AUDIO_INPUT_DEVICE", "-1"))
    )
    output_device_index: int = field(
        default_factory=lambda: int(_optional("AUDIO_OUTPUT_DEVICE", "-1"))
    )


# ---------------------------------------------------------------------------
# Deepgram STT constants
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class STTConfig:
    model: str            = "nova-2"  # Low-latency live turn tracking target
    language: str         = "en-US"
    punctuate: bool       = True
    interim_results: bool = True
    endpointing: int      = 300          # ms of silence before utterance_end
    utterance_end_ms: int = 1_000
    sample_rate: int      = 48000
    channels: int         = 1


# ---------------------------------------------------------------------------
# Deepgram TTS constants
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TTSConfig:
    model: str       = "aura-2-odysseus-en"  # Your optimized male voice profile
    encoding: str    = "linear16"
    sample_rate: int = 24000
    container: str   = "none"               # raw PCM — no WAV header overhead


# ---------------------------------------------------------------------------
# LLM constants
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LLMConfig:
    model: str         = "gemini-2.5-flash"  # Upgraded engine specification
    temperature: float = 0.4                 # Lowered for corporate response consistency
    max_tokens: int    = 512
    system_prompt: str = (
        "You are an elite, professional AI Solutions Architect representing ABT Plus LLC "
        "(Automated Business Technologies), a US-registered tech startup found at www.abtplusllc.com. "
        "Our core competencies include high-performance private AI automation pipelines, "
        "multi-agent workflow engineering, multi-platform scrapers for B2B lead extraction, "
        "and custom local LLM hosting layouts using Ollama and Mistral to eliminate high "
        "cloud fees and keep company data completely private. "
        "Our upcoming features include Smartech, an intelligent scraper instance designed "
        "to scan massive job matrices and automatically qualify high-value B2B outbound prospects. "
        "You must speak in a professional, technical, yet highly clear conversational style. "
        "Keep your responses tightly constrained to only 1 to 2 sentences max, and stay "
        "under 120 characters whenever possible so the caller can easily respond. "
        "Crucial instruction: Never use any markdown formatting, asterisks, bullet points, "
        "links, or bold text in your output, as your responses will be read aloud over audio. "
        "If a prospect shows technical interest, immediately drive the conversation to close "
        "for the meeting by asking them if they would like to book an enterprise discovery "
        "session with our core systems engineer."
    )


# ---------------------------------------------------------------------------
# Pipeline tuning
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PipelineConfig:
    # asyncio.Queue max sizes (0 = unbounded, not recommended in production)
    stt_queue_maxsize: int  = 16
    llm_queue_maxsize: int  = 16
    tts_queue_maxsize: int  = 32

    # Graceful-shutdown drain timeout (seconds)
    shutdown_timeout: float = 5.0


# ---------------------------------------------------------------------------
# Root config object — single source of truth
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Config:
    keys:     APIKeys     = field(default_factory=APIKeys)
    audio:    AudioConfig = field(default_factory=AudioConfig)
    stt:      STTConfig   = field(default_factory=STTConfig)
    tts:      TTSConfig   = field(default_factory=TTSConfig)
    llm:      LLMConfig   = field(default_factory=LLMConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)


def load_config() -> Config:
    """Validate and return a frozen Config instance. Raises on missing keys."""
    cfg = Config()
    log.info(
        "Config loaded | STT model=%s | LLM model=%s | TTS model=%s",
        cfg.stt.model,
        cfg.llm.model,
        cfg.tts.model,
    )
    return cfg
