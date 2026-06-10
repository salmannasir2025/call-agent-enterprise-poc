# Graph Report - call agent  (2026-06-10)

## Corpus Check
- 9 files · ~145,377 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 139 nodes · 258 edges · 15 communities (14 shown, 1 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 39 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ee880dd3`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]

## God Nodes (most connected - your core abstractions)
1. `AudioOutputRouter` - 22 edges
2. `VoicePipeline` - 20 edges
3. `CallAgentUI` - 13 edges
4. `AudioQueue` - 12 edges
5. `managed_input_router()` - 12 edges
6. `Config` - 12 edges
7. `AudioInputRouter` - 10 edges
8. `_amain()` - 10 edges
9. `STTWorker` - 10 edges
10. `LLMWorker` - 10 edges

## Surprising Connections (you probably didn't know these)
- `QCloseEvent` --uses--> `VoicePipeline`  [INFERRED]
  ui_main.py → pipeline.py
- `AudioQueue` --uses--> `AudioConfig`  [INFERRED]
  audio_router.py → config.py
- `ClientSession` --uses--> `AudioQueue`  [INFERRED]
  pipeline.py → audio_router.py
- `LLMWorker` --uses--> `AudioQueue`  [INFERRED]
  pipeline.py → audio_router.py
- `AudioQueue` --uses--> `AudioQueue`  [INFERRED]
  pipeline.py → audio_router.py

## Import Cycles
- 1-file cycle: `pipeline.py -> pipeline.py`

## Communities (15 total, 1 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.14
Nodes (15): list_audio_devices(), managed_input_router(), managed_output_router(), audio_router.py — Sounddevice stream initialization, buffer handling,, Instantly mutes AI audio and flushes the hardware ring buffer.          Sets the, Log all available Sounddevice host devices for debugging / device mapping., Return the device index to pass to Sounddevice.     -1 sentinel → None (use syst, resolve_device_index() (+7 more)

### Community 1 - "Community 1"
Cohesion: 0.22
Nodes (6): QThread, check_single_instance_or_notify(), main(), PipelineRunner, SingleInstanceServer, UILogHandler

### Community 2 - "Community 2"
Cohesion: 0.19
Nodes (5): QCloseEvent, QMainWindow, CallAgentUI, Founder takeover: instantly silence AI, purge queues., Re-enable AI audio after a founder intercept.

### Community 3 - "Community 3"
Cohesion: 0.21
Nodes (6): AbstractEventLoop, AudioInputRouter, AudioOutputRouter, Opens a Sounddevice input stream and feeds raw PCM chunks into an asyncio Queue., AudioConfig, AudioConfig

### Community 4 - "Community 4"
Cohesion: 0.20
Nodes (8): APIKeys, LLMConfig, PipelineConfig, config.py — Environment parsing, validation, and runtime constants. All secrets, Raise EnvironmentError if key is absent or empty., _require(), STTConfig, TTSConfig

### Community 5 - "Community 5"
Cohesion: 0.20
Nodes (5): Owns all three workers and their inter-stage queues.     Call `run()` from the a, Graceful shutdown: inject sentinel, then wait for drain., Instantly silences AI output and purges all pending queues.          Call this w, Re-enables AI audio output after a hot interrupt., VoicePipeline

### Community 6 - "Community 6"
Cohesion: 0.20
Nodes (9): About ABT Plus LLC, 📊 Architectural Workflow, 📬 Contact & Corporate Information, Core Capabilities Highlighted, Enterprise Voice-to-Voice AI Agent (Proof of Concept), Future Integration: Smartech B2B Infrastructure, ⚖️ Open-Source Academic Licensing & Disclaimer, Overview (+1 more)

### Community 7 - "Community 7"
Cohesion: 0.25
Nodes (5): AudioOutputRouter, Reads raw PCM bytes from an asyncio Queue and writes them to a Sounddevice     o, Write PCM chunk — silently dropped if abort flag is set., Re-enables PCM writes after a hot interrupt., Return True if hardware sound device is actively playing written buffer.

### Community 8 - "Community 8"
Cohesion: 0.46
Nodes (4): AudioQueue, AudioOutputRouter, Config, Queue

### Community 9 - "Community 9"
Cohesion: 0.32
Nodes (5): Config, AudioQueue, pipeline.py — Asyncio core loop orchestrating STT → LLM → TTS.  Stage topology (, Consumes raw PCM from `audio_queue`, forwards to Deepgram Live STT,     and push, STTWorker

### Community 10 - "Community 10"
Cohesion: 0.43
Nodes (4): ClientSession, Consumes text chunks from `tts_text_queue`, synthesizes PCM audio      via Deepg, Apply a smooth linear fade-out to the final samples of a PCM chunk., TTSWorker

### Community 11 - "Community 11"
Cohesion: 0.33
Nodes (4): LLMWorker, Consumes transcripts from `transcript_queue`, streams responses from     Gemini, Stream Gemini response without blocking the asyncio event loop.          FIX: Th, Isolated synchronous disk writer — always called from thread pool only.

## Knowledge Gaps
- **14 isolated node(s):** `APIKeys`, `STTConfig`, `TTSConfig`, `LLMConfig`, `PipelineConfig` (+9 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `VoicePipeline` connect `Community 5` to `Community 0`, `Community 1`, `Community 2`, `Community 7`, `Community 8`, `Community 9`?**
  _High betweenness centrality (0.282) - this node is a cross-community bridge._
- **Why does `AudioOutputRouter` connect `Community 7` to `Community 0`, `Community 3`, `Community 5`, `Community 8`, `Community 9`, `Community 10`, `Community 11`?**
  _High betweenness centrality (0.201) - this node is a cross-community bridge._
- **Why does `CallAgentUI` connect `Community 2` to `Community 0`, `Community 1`, `Community 5`?**
  _High betweenness centrality (0.130) - this node is a cross-community bridge._
- **Are the 10 inferred relationships involving `AudioOutputRouter` (e.g. with `AudioConfig` and `ClientSession`) actually correct?**
  _`AudioOutputRouter` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `VoicePipeline` (e.g. with `_ShutdownController` and `AudioOutputRouter`) actually correct?**
  _`VoicePipeline` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `AudioQueue` (e.g. with `AudioConfig` and `ClientSession`) actually correct?**
  _`AudioQueue` has 10 INFERRED edges - model-reasoned connections that need verification._
- **What connects `audio_router.py — Sounddevice stream initialization, buffer handling,`, `Log all available Sounddevice host devices for debugging / device mapping.`, `Return the device index to pass to Sounddevice.     -1 sentinel → None (use syst` to the rest of the system?**
  _41 weakly-connected nodes found - possible documentation gaps or missing edges._