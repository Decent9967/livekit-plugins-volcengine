# Roadmap

Staged plan for this repository. Gated items name their trigger and are done when the trigger fires — not speculatively.

## v0.1.0 — first public release

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

## v0.2.0 — capability qualification (current)

- Typed speaker/LID and acoustic/trait toggles; standard SpeechData fields and namespaced metadata.
- Full-mode repeated-sentence replay and corpus control experiment.
- Provider duration investigated; local transmitted-audio accounting retained.
- [Qualification results and limits](docs/validation-0.2.0.md).

## Deferred, with evidence triggers

- More LID mappings: representative dialect/singing responses plus unambiguous language tags.
- Trait accuracy: representative consenting real-person data and a concrete use case.
- Provider billing reconciliation: documented charge semantics and complete acknowledgements.
- Image/POI/music: a real consumer and controlled validation.
- Seamless configuration updates: actual mid-speech update demand; current reconnect can discard a partial audio tail.
- Keepalive: reproduced idle disconnect and a ping-responsive gateway.

## Next candidate — bidirectional TTS

- Implemented locally: PCM TTS, SDK lifecycle integration and provider usage;
  [scope and evidence](docs/tts.md).
- Release gate: TTS service access, real audio/cancel/next-reply validation and
  backend microphone E2E. Access and four VV-voice provider smoke cases now pass;
  backend microphone E2E passes for Chinese, English, interruption and recovery.
- Idle reuse: SDK connection-age retirement passes real 0/10/30/60-second probes
  with retries disabled; see docs/tts.md for the policy and evidence limits.
- Ten VV listening samples accepted by the user; see docs/tts.md for scope.
- Remaining release work: consumer
  regression against the published version without PYTHONPATH overrides.
- TTS is assigned v0.3.0 after the VV listening and idle-reuse qualification.

TTS candidate now also models filters, language/dialect, pronunciation, pitch,
LaTeX, audible watermark, caller-owned section IDs and subtitle events. Seven
real VV requests verified audio/subtitle responses; see docs/tts.md for limits
and the emoji flag discrepancy. Other controls still need live qualification.

## Community contribution — upstreaming into livekit/agents

- Port tests to monorepo conventions (`tests/test_plugin_volcengine_stt.py`; study the `toxic_proxy` / `fake_stt` / `virtual_time` fixtures).
- Proposal issue referencing the 29-plugin implementation audit, the parameter coverage table, and the differentiators listed in the README.
- If accepted upstream: archive this repository as the historical home.
