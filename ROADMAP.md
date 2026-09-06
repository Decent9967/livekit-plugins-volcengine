# Roadmap

Staged plan for this repository. Gated items name their trigger and are done when the trigger fires — not speculatively.

## v0.1.0 — first public release (current)

Done and unit-tested (44 tests):

- Streaming STT over the v3 `bigmodel_async` WebSocket: two-pass finals, full result/utterance traversal, server error frames surfaced as `APIStatusError`, reconnection delegated to the framework retry loop.
- Layered module split — `protocol` / `_options` / `_capabilities` / `_transcript` / transport — see [DESIGN.md](DESIGN.md).
- Capability registry: composition-time requirement checks; turn-detection hazards and partially wired escape-hatch bundles warn at construction.
- `update_options` hot-swap (STT-level fan-out → per-stream reconnect) with per-stream option snapshots.
- `RECOGNITION_USAGE` events: local audio accounting, 5-second batches, flushed at stream end and on connection teardown (quiescence).
- Connect-path error mapping (handshake rejection → `APIStatusError`, timeout → `APIConnectionError`), never leaking the API key through chained exceptions.
- Response mapping: `words[]` → `SpeechData.words`, ms→s timestamp conversion, `start_time_offset` timeline alignment, language from options (no hardcoding in the mapper).
- Escape hatch merges last and can override first-class values (pinned by test); unrecognized response fields are observable at debug level.
- `corpus.context` / `sensitive_words_filter` auto-serialization to the JSON strings the API expects.

Remaining gates for the 0.1.0 tag:

- [ ] E2E checklist against a live account (`tests/e2e/CHECKLIST.md`, 13 observations).
- [ ] Draft the upstream proposal issue.

## v0.2 — production hardening

| Item | Trigger |
|---|---|
| WebSocket keepalive (`ws_connect(heartbeat=...)`, one line) | E2E item 7 observes idle disconnects **and** the gateway answers pings — a client heartbeat against a ping-deaf gateway would *cause* drops |
| Speaker separation first-class: `enable_speaker_info` + `ssd_version` params, `SpeechData.speaker_id` mapping — graduated as **one bundle** (flag + hidden `ssd_version` + `show_utterances` + language-unset constraint) so the companion settings can't drift apart | in-production verification that separation works under the production parameter set |
| Response mapping batch: `additions` tags (language/emotion/gender/age) → `SpeechData.metadata` + framework `stt_context`; detected language replaces the hardcoded `zh-CN` (LID enum → BCP-47 translation table); `audio_info.duration` reconciles `RECOGNITION_USAGE` server-side; `result_type=full` support in the mapper (currently single-mode semantics — a full-mode cumulative payload would re-emit per response) | none — pure mapping over data already returned; exact `additions` placement confirmed during E2E. (`words[]` → `SpeechData.words` and the ms→s timestamp conversion already shipped in v0.1.) |
| Metadata tag params first-class (`show_speech_rate`, `show_volume`, `enable_lid`, `enable_emotion_detection`, `enable_gender_detection`, `enable_age_detection`) | ships together with the mapping batch above |
| Energy gating — skip silent audio before send (gladia-style, a billing optimization) | only if billing is confirmed to charge silent audio |

Parameter-level progress against the full official request surface is tracked in [PARAMETERS.md](PARAMETERS.md) ("Coverage vs the official request surface"): 23/33 first-class today, 33/33 reachable via `extra_request_params`.

## v0.3+ — upstreaming into livekit/agents

- Port tests to monorepo conventions (`tests/test_plugin_volcengine_stt.py`; study the `toxic_proxy` / `fake_stt` / `virtual_time` fixtures).
- Proposal issue referencing the 29-plugin implementation audit, the parameter coverage table, and the differentiators listed in the README.
- If accepted upstream: archive this repository as the historical home.
