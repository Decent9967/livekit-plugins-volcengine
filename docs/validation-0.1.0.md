# v0.1.0 validation evidence

Date: 2026-09-09. This is protocol/integration validation, not a field accuracy benchmark.

## Validated profile

- LiveKit Agents 1.6.10, Python 3.12 on Windows.
- `volc.seedasr.sauc.duration`, v3 `bigmodel_async`.
- 16 kHz, mono, 16-bit PCM, two-pass recognition, single result mode.
- ITN, punctuation, DDC enabled; end window 800 ms; speaker separation disabled.

## Evidence

- 54 offline tests cover framing, options, transcript events, cancellation,
  hot-update reconnect, usage, and error mapping.
- Current backend plugin and this candidate processed the same synthetic Chinese
  shopping utterances through the real service. Both produced exactly the same
  two final transcripts and ended normally. This is not a latency benchmark.
- The service returned object-shaped `result`; the archived reference describes
  a list. Both shapes are accepted. The sanitized response fixture is replayed
  in tests; no customer audio or account credentials are included.
- After 65 seconds of continuously streamed silent PCM, the same two sentences
  were recognized again; all four expected finals arrived and the stream ended.
  This does not test a connection with no audio packets at all.
- An intentionally invalid key raised `APIStatusError` with no transcript.
- Backend integration tests exercise actual LiveKit FallbackAdapter and actual
  primary/secondary plugins, with primary failure injected and a local server
  implementing the Sherpa wire protocol. They prove fallback routing and event
  delivery, not the Sherpa model's recognition accuracy.
- Hot-update tests await an observable reconnect event rather than assuming a
  10 ms scheduler deadline. Connection-local deduplication permits the same
  sentence after reconnect.

## Not established by this release

- Real retail microphone/noise/accent accuracy or browser-to-agent end-to-end UX.
- Live speaker separation, legacy ASR 1.0 resources, language/emotion/gender metadata.
- Live throttling behavior, actual billing reconciliation, hotword quality,
  or recovery under real network disruption (failure paths are tested offline).
- Naturally occurring empty finals were not observed in this speech sample;
  the event behavior is covered by synthetic unit tests.

The public constructor exposes additional request options; availability of an
escape hatch is not a claim that all associated response fields are mapped.
