# Capability evidence — 2026-09-09 (unreleased)

## Goal and minimum scope

Expose the provider's existing speaker/language results through standard LiveKit
SpeechData and make provider request correlation possible. No new event bus,
speaker identity store, retry mechanism, context injection, or production default
change is needed. Inputs and output mappings graduate together.

## Evidence levels

1. Official source: [bidirectional ASR API](https://docs.volcengine.com/docs/6561/2630027),
   opened 2026-09-09; page reports last updated 2026-09-01 15:27:25. It requires
   show_utterances for speaker output, recommends ASR 2.0, and its response example
   places speaker_id inside utterance additions. It does not specify ssd_version
   or a language-unset prerequisite. Earlier hidden-flag requirements are removed.
   The rendered LID detail was incomplete during this read; the repository's dated
   September 1 snapshot lists language/scene labels. Actual mappings below are
   independently confirmed by service responses.
2. Project experiment: live `volc.seedasr.sauc.duration`, 16kHz mono PCM, two-pass,
   single-result mode, 800ms endpoint, speaker and LID enabled; no ssd_version.
   System.Speech Huihui reads two Chinese shopping sentences, followed by 1.5s
   silence and Zira reading two English shopping sentences. Four finals complete
   in approximately 18 seconds. Chinese additions: speaker_id="0", lid_lang=
   "speech_mand"; English: speaker_id="1", lid_lang="speech_en".
3. Offline contract: replay the sanitized complete response stream through the
   mapper, checking four finals, speaker IDs and languages. Dedicated tests cover
   pending-final preservation, missing/invalid tags, escape overrides, and logs.

This verifies field transport and mapping using synthetic voices, not diarization
accuracy in overlapping real speech or business identity binding. ID continuity
across reconnects is not promised. ASR 1.0, concurrency billing resource, dialects,
singing labels, metadata traits and corpus effectiveness remain unverified.

## Delivered matrix

| Capability | Minimum mechanism | Acceptance / next trigger |
|---|---|---|
| Speakers | Optional typed flag; additions → standard speaker_id | IDs 0/1 survive interim/final; malformed absent values do not become IDs |
| LID | Optional typed flag; two verified label mappings | Mandarin → zh-CN, English → en; unknown retains caller fallback |
| Diagnostics | DEBUG record containing log_id and request_id | No transcript, API key or full response in that record |
| Other metadata | Keep escape hatch | Add when response samples and a useful consumer define the contract |
| Full results | Existing definite dedup | Live cumulative replay before recommending full mode |
| Usage | Existing local accounting | Prove server duration semantics before reconciling or calling it billing |
| Corpus | Existing request/reconnect | Controlled with/without comparison before asserting effectiveness |
| POI/music | Deferred | A real domain use case |

No release/tag, version bump, backend dependency change, or upstream submission
is included. Existing v0.1.0 installation remains unchanged.

Verification: 77 offline tests pass, Ruff lint/format pass, wheel and sdist build
successfully, and independent code review found no blocking issue. A second live
run using the typed options (rather than the escape hatch) completed with all four
finals mapped to speakers 0/0/1/1 and languages zh-CN/zh-CN/en/en.

## Reproducibility and privacy

`tests/fixtures/synthetic-bilingual.json` retains the full synthetic response
sequence and removes log_id/request_id/uid recursively. Its text is generated,
not a customer recording. The live probe uses an aiohttp session, pushes 100ms
frames at real time, ends input, and consumes events with SDK retries disabled.
Never commit credentials or raw provider identifiers. Re-run with an authorized
account to assess provider drift; the fixture proves mapper behavior only.
