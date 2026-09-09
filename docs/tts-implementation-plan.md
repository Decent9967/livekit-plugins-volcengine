# Bidirectional TTS implementation plan

## Accepted scope

Add `volcengine.TTS` beside STT using the official V3 bidirectional endpoint.
Keep ASR framing unchanged. Reuse LiveKit 1.6.10 input replay, audio emission,
connection pooling and cancellation ownership, not the old fork's private replay.
PCM mono is the initial audio contract; complete text and incremental text use
the same transport. No voice-management API, automatic fallback, subtitles or
automatic cross-turn context in this change.

## Implementation and acceptance

- [x] Codec: independent `_tts_protocol.py`; test connection/session/audio/error
  frames and malformed lengths before implementation.
- [x] Adapter: `tts.py` and request options; test local WebSocket transport with
  real SDK emitters: incremental and complete input, flush, reuse, cancellation,
  retries before audio, no retry after audio, errors, timeout and empty input.
- [x] Usage: expose provider `SessionFinished.usage` separately from SDK input
  characters and tokens. Never infer missing usage or a billing price.
- [x] Integration: backend selects Matcha (unchanged default) or Volcengine,
  YAML owns parameters, environment owns TTS credentials. Verify local candidate
  through PYTHONPATH until an immutable plugin release is approved.
- [x] Live probe: use the previously authorized local credentials without
  printing them; record actual synthesis/cancellation/usage results or exact
  missing access. Microphone E2E is a separate evidence level.
- [x] Run regression and formatting checks; independent code review; document
  supported parameters and remaining release work. No commit/tag/push here.

Sources: https://docs.volcengine.com/docs/6561/2532486?lang=zh,
https://docs.livekit.io/agents/models/tts/ and locked livekit-agents 1.6.10 source.
Prior art: backend Apache-2.0 bytedance V3 TTS implementation and regression tests.

Result: 144 plugin tests pass; TTS files have 93-94% statement coverage. Ruff
0.16.6 lint/format checks pass. Wheel/sdist build includes TTS modules and NOTICE.
Backend candidate integration: 102 passed / 3 real-service E2E skipped; config,
architecture, logging, deployment and ADR checks pass. Independent review passes
for the development candidate. After service activation, four real VV-voice
provider smoke cases pass (complete, incremental, cancel, next reply).
Microphone/browser E2E now passes for Chinese, English, interruption and next-reply
recovery; see docs/tts.md for evidence limits. Idle pooled-connection retirement
now passes focused real probes with retries disabled. The user accepted ten VV
listening samples. Published-version consumer qualification remains open.
No production enablement or release occurred.

## Typed TTS controls follow-up (user-approved)

- [x] Add optional named filters, language/dialect, pronunciation rules, pitch,
  LaTeX, audible watermark and caller-owned section_id using existing request assembly.
- [x] Add subtitle request flag and session-correlated raw subtitle events (official code 364).
- [x] Validate effective named/additions combinations, preserve false/zero and input isolation.
- [x] Run regression and seven real VV filter/pronunciation/subtitle requests.
- [x] Retire aged pooled connections using the SDK; 174 plugin tests and real
  0/10/30/60-second idle probes pass without retries.
- [x] User listening acceptance of ten VV numbers, mixed-language, filter and pronunciation samples.
- [ ] Remaining voice-specific controls qualification (outside the ten accepted samples).

The new API does not expand backend configuration, business prompts, playback,
retry or session ownership. No new local text normalization or phonetic engine.
See docs/tts.md for the emoji documentation/service discrepancy. Provider-specific
controls are not all live-qualified merely because wire tests pass.
