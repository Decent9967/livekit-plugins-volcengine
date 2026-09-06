# livekit-plugins-volcengine

Volcengine (Doubao) streaming speech recognition (ASR) plugin for [LiveKit Agents](https://github.com/livekit/agents) — v3 `bigmodel_async` bidirectional WebSocket, implemented from the [public API reference](https://docs.volcengine.com/docs/6561/2630027).

Status: **v0.1 in development** — STT implemented and unit-tested (15 tests); E2E validation against a live account in progress (see `tests/e2e/CHECKLIST.md`). API may change before 0.1.0.

## Why another Volcengine plugin

Existing community adapters exist but fall short of what production voice agents need. Differences in this implementation, each backed by a unit test or a filed repro:

- **Server errors are surfaced, not swallowed.** `SERVER_ERROR_RESPONSE` frames raise `APIStatusError` with the server error code and payload. In adapters that ignore them, an auth or quota failure looks like a silent stall until timeout.
- **Empty two-pass finals close the turn.** With `enable_nonstream`, `definite: true` arrives from the second pass — sometimes with empty text (no speech in the segment). That still emits `END_OF_SPEECH`; dropping it stalls downstream turn detection.
- **Full result traversal.** Every `result` entry and every `utterance` is emitted, not just the first.
- **Reconnection delegated to the framework.** Unexpected close raises `APIConnectionError(retryable=True)` and reconnection runs through the standard `conn_options` retry loop — no hand-rolled, untested reconnect path.
- **Current request surface + escape hatch.** Options cover the documented parameters (two-pass, VAD tuning, first-token acceleration, sensitive words, hotwords/`corpus`, traditional-Chinese variants) and `extra_request_params` merges into the request payload last, so new server-side parameters work without waiting for a plugin release.

## Install

```bash
pip install livekit-plugins-volcengine
```

> The PyPI distribution name is still being finalized (a third party currently publishes an unrelated package under this name). Until then, install from a git ref.

## Usage

```python
from livekit.agents import AgentSession
from livekit.plugins.volcengine import STT

session = AgentSession(
    stt=STT(
        # api_key=... or set VOLCENGINE_API_KEY
        resource_id="volc.seedasr.sauc.duration",  # ASR 2.0 (default, recommended)
        enable_nonstream=True,  # two-pass: fast interim + accurate finals
        end_window_size=800,  # VAD silence threshold (ms)
    ),
    # llm=..., tts=...
)
```

Roadmap: speaker separation passthrough (`enable_speaker_info` + `ssd_version`, pending `SpeechData.speaker_id` alignment across livekit-agents versions), metadata params (emotion/gender/age/LID).

## Development

```bash
uv sync --dev
uv run pytest
uv run ruff check .
```

E2E runs against a personal Volcengine account; see `tests/e2e/` (in progress).

## License

Apache-2.0
