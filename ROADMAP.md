# Roadmap

Staged plan for this repository. Gated items name their trigger and are done when the trigger fires — not speculatively.

## v0.1.0 — first public release (current)

Implemented and covered by offline tests:

- Streaming STT over the v3 `bigmodel_async` WebSocket: two-pass finals, full result/utterance traversal, server error frames surfaced as `APIStatusError`, reconnection delegated to the framework retry loop.
- Layered module split — `protocol` / `_options` / `_capabilities` / `_transcript` / transport — see [DESIGN.md](DESIGN.md).
- Capability registry: composition-time requirement checks; turn-detection hazards and partially wired escape-hatch bundles warn at construction.
- `update_options` hot-swap (STT-level fan-out → per-stream reconnect) with per-stream option snapshots.
- `RECOGNITION_USAGE` events: local audio accounting, 5-second batches, flushed at stream end and on connection teardown (quiescence).
- Connect-path error mapping (handshake rejection → `APIStatusError`, timeout → `APIConnectionError`), never leaking the API key through chained exceptions.
- Response mapping: `words[]` → `SpeechData.words`, ms→s timestamp conversion, `start_time_offset` timeline alignment, language from options (no hardcoding in the mapper).
- Escape hatch merges last and can override first-class values (pinned by test); unrecognized response fields are observable at debug level.
- `corpus.context` / `sensitive_words_filter` auto-serialization to the JSON strings the API expects.

Scope of the 0.1.0 tag:

- The default ASR 2.0 / PCM / two-pass profile is validated against a live account;
  results and remaining observations from the broader checklist are tracked in
  [validation evidence](docs/validation-0.1.0.md). Untested optional capabilities
  are not claimed as production-validated.
- An [upstream proposal draft](docs/upstream-proposal.md) is prepared; submission
  is separate from this standalone release.

## Unreleased — first capability batch

Typed speaker/LID options, verified result mapping, and log_id diagnostics are implemented.
See [capability evidence](docs/capabilities-2026-09-09.md). This is not a release
or a backend dependency update.

## Later — evidence-gated hardening

| Item | Trigger |
|---|---|
| WebSocket keepalive (`ws_connect(heartbeat=...)`, one line) | E2E item 7 observes idle disconnects **and** the gateway answers pings — a client heartbeat against a ping-deaf gateway would *cause* drops |
| Response mapping batch: metadata tags and server-side usage; full-result mode validation | A real consumer needs these fields and representative response fixtures are available. v0.1 deduplicates definite utterances within a connection, but full-result mode is not live-validated. |
| Metadata tag params first-class (`show_speech_rate`, `show_volume`, `enable_emotion_detection`, `enable_gender_detection`, `enable_age_detection`) | ships together with the mapping batch above |
| Energy gating — skip silent audio before send (gladia-style, a billing optimization) | only if billing is confirmed to charge silent audio |

Parameter-level progress against the full official request surface is tracked in [PARAMETERS.md](PARAMETERS.md) ("Coverage vs the official request surface"): typed inputs, mapped outputs, and live validation are recorded separately.

## v0.3+ — upstreaming into livekit/agents

- Port tests to monorepo conventions (`tests/test_plugin_volcengine_stt.py`; study the `toxic_proxy` / `fake_stt` / `virtual_time` fixtures).
- Proposal issue referencing the 29-plugin implementation audit, the parameter coverage table, and the differentiators listed in the README.
- If accepted upstream: archive this repository as the historical home.
