# livekit-plugins-volcengine

Volcengine (Doubao) streaming speech recognition (ASR) plugin for [LiveKit Agents](https://github.com/livekit/agents) — v3 `bigmodel_async` bidirectional WebSocket, implemented from the [public API reference](https://docs.volcengine.com/docs/6561/2630027).

Status: **v0.1 in development** — STT implemented and unit-tested (44 tests); E2E validation against a live account in progress (see `tests/e2e/CHECKLIST.md`). API may change before 0.1.0.

## Why another Volcengine plugin

Existing community adapters exist but fall short of what production voice agents need. Differences in this implementation, each backed by a unit test or a filed repro:

- **Server errors are surfaced, not swallowed.** `SERVER_ERROR_RESPONSE` frames raise `APIStatusError` with the server error code and payload. In adapters that ignore them, an auth or quota failure looks like a silent stall until timeout.
- **Empty two-pass finals close the turn.** With `enable_nonstream`, `definite: true` arrives from the second pass — sometimes with empty text (no speech in the segment). That still emits `END_OF_SPEECH`; dropping it stalls downstream turn detection.
- **Full result traversal.** Every `result` entry and every `utterance` is emitted, not just the first.
- **Reconnection delegated to the framework.** Unexpected close raises `APIConnectionError(retryable=True)` and reconnection runs through the standard `conn_options` retry loop — no hand-rolled, untested reconnect path.
- **Combination-safe by construction.** Capability requirements (what turn detection needs, what a speaker-separation bundle needs) live in a registry and are checked at construction — invalid option combinations and partially wired escape-hatch bundles warn immediately instead of failing silently mid-conversation (see [DESIGN.md](DESIGN.md)).
- **Current request surface + escape hatch.** Options cover the documented parameters (two-pass, VAD tuning, first-token acceleration, sensitive words, hotwords/`corpus`, traditional-Chinese variants) and `extra_request_params` merges into the request payload last — it can even override first-class values, so new or changed server parameters work without waiting for a plugin release.

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

Roadmap: [ROADMAP.md](ROADMAP.md) — staged plan with per-item triggers. Parameter coverage against the official request surface: [PARAMETERS.md](PARAMETERS.md). Architecture: [DESIGN.md](DESIGN.md).

Full parameter reference: [PARAMETERS.md](PARAMETERS.md).

## Development

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

E2E runs against a personal Volcengine account; see `tests/e2e/` (in progress).

## Sources

The wire-protocol facts this plugin implements trace to public Volcengine artifacts, archived with hashes in [`refs/`](refs/README.md) so upstream changes can be diffed.

## License

Apache-2.0
