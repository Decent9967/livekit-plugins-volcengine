# Changelog

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
