# Parameters reference

All parameters are passed to the `STT` constructor; every one has a default, so the minimum working setup only needs an API key. Parameters unknown to this plugin can still be sent — see [Escape hatch](#escape-hatch-extra_request_params) at the bottom.

> Validation status: defaults marked ⏳ are pending live E2E verification (see `tests/e2e/CHECKLIST.md`); all others are covered by unit tests.

## Connection

| Parameter | Type | Default | Description |
|---|---|---|---|
| `api_key` | str | `VOLCENGINE_API_KEY` env | Volcengine API key from the console. Required (param or env). |
| `resource_id` | str | `volc.seedasr.sauc.duration` | Model version. 2.0 (recommended): `volc.seedasr.sauc.duration` / `.concurrent`. 1.0: `volc.bigasr.sauc.duration` / `.concurrent`. |
| `base_url` | str | `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async` | WebSocket endpoint. |

## Recognition behavior

| Parameter | Type | Default | Description |
|---|---|---|---|
| `model_name` | str | `bigmodel` | Service currently accepts only `bigmodel`. |
| `language` | str \| None | None | Recognition language (e.g. `zh-CN`, `en-US`). Unset = default zh/en model — also the path required for speaker separation. |
| `enable_nonstream` | bool | **True** | Two-pass recognition: fast interim results plus accurate `definite` finals. This plugin's final/turn-end handling assumes two-pass semantics. |
| `enable_itn` | bool | True | Inverse text normalization ("一九七零年" → "1970 年"). Matches the documented default. |
| `enable_punc` | bool | True | Punctuation. Matches the documented default. |
| `enable_ddc` | bool | False | Semantic smoothness (removes fillers/repeats). |
| `result_type` | str | **single** | `single` = incremental per-utterance results (what conversational agents want). `full` = cumulative re-sends of the whole session text. ⏳ |
| `interim_results` | bool | True | Whether interim transcripts are emitted as events at all. |

## Endpoint / VAD tuning

| Parameter | Type | Default | Description |
|---|---|---|---|
| `end_window_size` | int | 800 | VAD silence threshold (ms) that closes an utterance. Range [300, 5000]; recommended [800, 1000]. |
| `force_to_speech_time` | int | **1000** | Leading audio treated as speech (ms) to avoid premature stops at utterance start. Doc default is 0; we adopt the doc-recommended 1000. ⏳ |
| `vad_segment_duration` | int \| None | None | Max silence (ms) for semantic segmentation. Ignored by the service while `end_window_size` is set — only sent when you set it explicitly. |

## Extras

| Parameter | Type | Default | Description |
|---|---|---|---|
| `enable_accelerate_text` | bool | False | Faster first token, at a possible accuracy cost. |
| `accelerate_score` | int \| None | None | Acceleration rate; requires `enable_accelerate_text=True` (constructor raises otherwise). |
| `output_zh_variant` | str \| None | None | Traditional Chinese output: `traditional` / `tw` / `hk`. |
| `sensitive_words_filter` | dict \| None | None | Word filtering, e.g. `{"system_reserved_filter": True}`. Serialized to the JSON string the API expects. |
| `corpus` | dict \| None | None | Hotwords / replacement tables / dialog context (`context_type: "dialog_ctx"`, `image_url` for 2.0). A dict `context` is auto-serialized to the JSON string the API expects. Context + hotwords capped at 100 tokens upstream. Runtime-swappable via `update_options(corpus=...)`. |
| `extra_request_params` | dict | `{}` | Escape hatch — see below. |
| `audio_format` / `codec` / `bits` / `num_channels` | | pcm / raw / 16 / 1 | Audio encoding into the stream. |
| `http_session` | aiohttp.ClientSession \| None | None | Bring your own session (advanced). |

## Defaults that intentionally differ from the Volcengine docs

The upstream doc serves every use case (meeting captions, live subtitles, outbound calls); this plugin defaults are tuned for **conversational voice agents**, and every divergence is deliberate:

1. `result_type="single"` (doc default `full`) — agents consume finalized sentences; `full` re-sends the whole session text each frame and would flood the event stream with duplicates.
2. `enable_nonstream=True` (doc default `false`) — accurate `definite` finals drive turn-taking; the empty-final → `END_OF_SPEECH` handling also assumes two-pass semantics.
3. `force_to_speech_time=1000` (doc default `0`, doc-recommended `1000`) — prevents the first word of an utterance from being swallowed by premature VAD stops.

All three are covered by the E2E checklist.

## Escape hatch: `extra_request_params`

Anything this plugin does not model yet can be passed through directly — values merge into the `request` payload last:

```python
STT(
    ...,
    extra_request_params={
        "enable_speaker_info": True,
        "ssd_version": "200",
    },
)
```

Use it for newly added service parameters without waiting for a plugin release. Because it merges last, an entry whose name matches a first-class option **overrides** it — you can also use it to try changed server semantics before a plugin release. If a parameter turns out to be broadly useful, it will graduate into a first-class option (see `DESIGN.md` for the graduation path).

## Coverage vs the official request surface

Per-parameter checklist against the official field snapshot of 2026-09-01 (24 `request` fields + 5 `audio` + 3 headers + 1 hidden). Two independent axes — a parameter can be wired as input while its output is not consumed:

- **Input**: ✅ first-class constructor option · (blank) sendable only via `extra_request_params` · ❌ deliberately not integrated
- **Output consumed**: ✅ the response data this parameter controls is mapped into speech events · (blank) produced but dropped today (plan in [ROADMAP.md](ROADMAP.md)) · — parameter has no per-response output (it only shapes recognition at the source)

| Family | Field | Input | Output consumed | Notes |
|---|---|---|---|---|
| Headers | `X-Api-Key` | ✅ | — | |
| Headers | `X-Api-Resource-Id` | ✅ | — | `resource_id` |
| Headers | `X-Api-Request-Id` | ✅ | — | auto-generated per stream |
| Audio | `format` | ✅ | — | `audio_format` |
| Audio | `codec` | ✅ | — | |
| Audio | `rate` | ✅ | — | `sample_rate` |
| Audio | `bits` | ✅ | — | |
| Audio | `channel` | ✅ | — | `num_channels` |
| Recognition | `model_name` | ✅ | — | service accepts only `bigmodel` |
| Recognition | `enable_nonstream` | ✅ | ✅ | `definite` finals drive FINAL/END_OF_SPEECH |
| Recognition | `enable_itn` | ✅ | — | |
| Recognition | `enable_punc` | ✅ | — | |
| Recognition | `enable_ddc` | ✅ | — | |
| Recognition | `result_type` | ✅ | | event mapping assumes `single` (default); `full`-mode cumulative payloads would re-emit per response — do not use `full` until the mapper deduplicates |
| Recognition | `show_utterances` | ✅ | ✅ | utterances traversed; `words[]` → `SpeechData.words` |
| Recognition | `language` | ✅ | — | sent when set, per the pre-2.0 docs; not listed in the 9.1 field table |
| Endpoint / VAD | `end_window_size` | ✅ | — | |
| Endpoint / VAD | `vad_segment_duration` | ✅ | — | only sent when set explicitly |
| Endpoint / VAD | `force_to_speech_time` | ✅ | — | defaults 1000, the doc-recommended value |
| Text post-processing | `output_zh_variant` | ✅ | — | |
| Text post-processing | `sensitive_words_filter` | ✅ | — | |
| First-token boost | `enable_accelerate_text` | ✅ | — | |
| First-token boost | `accelerate_score` | ✅ | — | |
| Corpus | `corpus` (boosting / correct / regex-correct tables, `context`) | ✅ | — | biases recognition at the source; runtime-swappable via `update_options` |
| Speaker separation | `enable_speaker_info` | | | server would add `utterances[].speaker_id`; not mapped yet — v0.2 |
| Speaker separation | `ssd_version` (hidden, pre-2.0 docs) | | — | server-side enablement for the above |
| Metadata tags | `show_speech_rate` | | | `additions` speed tag dropped today — v0.2 |
| Metadata tags | `show_volume` | | | `additions` volume tag dropped today — v0.2 |
| Metadata tags | `enable_lid` | | | language/scene tags dropped; also the fix for the hardcoded `zh-CN` in `SpeechData.language` — v0.2 |
| Metadata tags | `enable_emotion_detection` | | | `additions` emotion tag dropped today — v0.2 |
| Metadata tags | `enable_gender_detection` | | | `additions` gender tag dropped today — v0.2 |
| Metadata tags | `enable_age_detection` | | | `additions` age tag dropped today — v0.2 |
| Domain function calls | `enable_poi_fc` | ❌ | ❌ | by design: map-domain toggle, and its suggestions need custom consumption logic anyway |
| Domain function calls | `enable_music_fc` | ❌ | ❌ | by design, same as above |

**Input: 23 ✅ / 8 escape-hatch / 2 ❌. Output consumed today: `text`, `definite`, `start_time`/`end_time` (ms→s), `confidence`, `words[]`. Everything else a parameter produces is marked above with its v0.2 plan.**

By-response-field view of the same gaps:

| Response field | Mapped today | Plan |
|---|---|---|
| `text`, `definite`, `start_time`, `end_time`, `confidence` | ✅ (ms → s, plus `start_time_offset`) | — |
| `utterances[].words[]` (already returned: `show_utterances` defaults on) | ✅ → `SpeechData.words` (`TimedString`) | — |
| `utterances[].speaker_id` | | → `SpeechData.speaker_id` (with the speaker-separation graduation) |
| `additions` (language / emotion / gender / age tags) | | → `SpeechData.metadata`, plus the framework `stt_context` hook for speaker-level traits |
| detected language → `SpeechData.language` | hardcoded `zh-CN` | → detected language (`enable_lid` tags need an enum→BCP-47 translation table) |
| `audio_info.duration` | | → server-side reconciliation of `RECOGNITION_USAGE` usage events |
| `additions.log_id` | | → log context for support tickets |

## Capability switches and their companion inputs

Some fields are only switches — alone they do nothing, or are ignored, or error. They must be configured together with their companion inputs:

| Switch | Requires | Status in this plugin |
|---|---|---|
| `enable_accelerate_text` | `accelerate_score` (rate value; optional) | enforced: score without the flag raises `ValueError`; flag alone uses the server default |
| `enable_speaker_info` | `show_utterances=true` + hidden `ssd_version="200"` + `language` unset (2.0) | escape hatch today; will graduate as **one bundle** with `SpeechData.speaker_id` mapping so the four settings can't drift apart |
| `corpus.context` → `dialog_ctx` | the dialog history itself (`context_data`), which **changes every turn** | accepted as static input today — but config is connection-scoped, so applying an update reconnects the stream. Fine for occasional hotword-table swaps; **not suitable for per-turn dialog context** until the service offers in-band config updates |
| `corpus.context` → `image_url` | `enable_nonstream=true`; 2.0 only; ≤1 image, ≤500 KB, jpg/png | sendable today; constraints unvalidated until E2E |
| `enable_poi_fc` / `enable_music_fc` | `enable_nonstream=true` | ❌ by design |
| `end_window_size` | VAD active (auto-enabled by `enable_nonstream`, `enable_lid`, …) | satisfied by default: this plugin enables `enable_nonstream` |

The `dialog_ctx` row is the notable one: the data is per-turn but the documented protocol has no mid-stream config update, so per-turn context injection would thrash reconnects. Whole-session context (e.g. product docs, agent persona) works today via the constructor or occasional `update_options`.

## Combination hazards

Can every declared capability be combined freely? **No.** Everything is sendable, but some combinations degrade this adapter's *event semantics* while the request itself stays valid. The constructor warns for each of the first four rows below, for non-`pcm` input, and for partially wired escape-hatch bundles (e.g. `enable_speaker_info` without `ssd_version`):

| Combination | What breaks | Why |
|---|---|---|
| `enable_nonstream=False` | No `FINAL_TRANSCRIPT`/`END_OF_SPEECH` mid-stream; only the trailing commit at stream end fires | `definite` results come exclusively from the two-pass second pass; the utterance state machine has nothing to close turns with |
| `show_utterances=False` | Same as above | `definite` lives on `utterances[]`; without them every result falls back to a synthetic interim-only utterance |
| `result_type="full"` | Duplicate emissions: cumulative payloads are re-mapped per response | mapper assumes `single` (incremental) semantics — see the coverage table |
| `audio_format` ≠ `pcm` | Server cannot decode the frames | audio pushed through LiveKit is raw PCM; container formats only make sense for pre-encoded payloads |
| metadata tags via escape hatch (LID/emotion/…) | No visible effect | the `additions` fields they produce are not consumed yet (v0.2) |
| `enable_speaker_info` without `show_utterances` | Server rejects or ignores | separation results ride on `utterances[]` |

The first two rows share one root cause: this adapter's turn model is two-pass-by-design. Disabling either leg is legitimate for caption-only use with an external VAD, which is why these warn rather than raise.
