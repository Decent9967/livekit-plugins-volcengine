# Changelog

## Unreleased

## 0.3.0

- Add V3 bidirectional `TTS`: incremental/complete text, PCM audio, lifecycle
  cleanup, SDK-owned retries and raw provider billing-character usage events.
- Add protocol fixtures from the official demo, local WebSocket regression
  tests and an opt-in real-service smoke script. Real audio qualification is
  completed for four VV-voice smoke cases and browser Chinese/English replies,
  interruption and recovery. The user accepted ten VV listening samples covering
  English numbers/symbols, mixed language, filters and pronunciation.
- Retire TTS pooled connections after 10 seconds of connection age at the next
  acquisition, using the SDK pool. Real 0/10/30/60-second idle probes pass with
  retries disabled; active synthesis is not interrupted by connection expiry.
- Add optional typed filters, language/dialect, pronunciation dictionary, pitch,
  LaTeX, audible watermark, caller-owned section IDs and raw subtitle events.
  Seven real VV control requests returned audio/subtitles; document the emoji
  flag discrepancy without silently inverting provider values.

## 0.2.0

- Typed speaker and language-identification options with standard SpeechData mappings.
- Typed acoustic/trait options and namespaced, normalized provider metadata.
- Provider log_id correlation through structured DEBUG logs.
- Full-result repeated-sentence qualification; removed obsolete full-mode warning.
- Corrected obsolete speaker prerequisites and added controlled corpus evidence.
- Retained local usage accounting after silence/reconnect comparison.

See `docs/validation-0.2.0.md` for evidence and limits. No PyPI publication.

## 0.1.0

Initial standalone GitHub release for the default ASR 2.0 streaming profile.

- Standard LiveKit STT events, options, usage accounting and framework retries.
- Object/list response compatibility backed by a real synthetic-speech fixture.
- Connection-local final deduplication and empty-final turn closure.
- Reliable terminal audio packet at exact chunk boundaries.
- WebSocket error propagation and structured provider error codes.
- Deterministic hot-update reconnect tests and backend fallback integration validation.

See `docs/validation-0.1.0.md` for evidence and unsupported/unverified profiles.
This release does not publish a PyPI package.
