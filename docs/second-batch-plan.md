# Second capability batch and release plan

Goal: validate optional provider behavior before the next standalone GitHub release.
Approved scope: full-result replay, acoustic/trait metadata sampling, provider duration
semantics, and controlled corpus comparison. Preserve the current backend dependency.

Architecture: reuse options, TranscriptMapper, SpeechData.metadata and SDK retries.
No new queue, identity state, metadata event bus, billing reconciliation or per-turn
corpus channel. Unknown/unverified fields remain explicitly unsupported.

Tech stack: Python >=3.10, LiveKit Agents >=1.6.10,<2.0, aiohttp, pytest, Ruff.

- [ ] Sample the official API with synthetic speech: single/full, metadata enabled,
  quieter/faster audio, silent audio, and the same corpus audio with/without context.
  Record effective options, audio duration, raw sanitized responses and final events.
- [ ] Replay full responses offline. Assert the same ordered finals as single mode
  and balanced speech boundaries. Add failing regressions for any observed defect
  before changing `_transcript.py`.
- [ ] Map only observed metadata keys under `SpeechData.metadata`; test missing,
  malformed and pending-final values first. Add matching typed options in `_options.py`
  and `stt.py`, preserving default payloads and last-wins escape overrides.
- [ ] Compare provider duration against PCM duration and existing local usage,
  including silence and reconnect reset. Retain local usage unless evidence proves
  a better contract. Document corpus control results without claiming broad accuracy.
- [ ] Run `pytest`, `ruff check .`, `ruff format --check .`, `uv build`, independent
  code review and a live candidate smoke test. Record exact validation limits.
- [ ] Prepare 0.2.0 changelog/version, push reviewed branch and PR, wait for CI,
  merge and create immutable GitHub tag/release with wheel/sdist. No PyPI or backend
  dependency upgrade in this scope.

Release gates: no reproducible duplicate/lost final in the supported tested profile;
all tests and CI pass; optional metadata is useful and traceable to real responses;
remaining provider limitations are explicit. A deficient optional feature may remain
escape-hatch-only rather than holding the basic streaming release indefinitely.
