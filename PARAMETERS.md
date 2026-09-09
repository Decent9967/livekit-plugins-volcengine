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
| `language` | str \| None | None | Recognition language (e.g. `zh-CN`, `en-US`). Unset = default zh/en model. |
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

1. `result_type="single"` (doc default `full`) — agents consume finalized sentences; `full` re-sends cumulative results and remains outside the live-validated profile, despite definite-result deduplication.
2. `enable_nonstream=True` (doc default `false`) — accurate `definite` finals drive turn-taking; the empty-final → `END_OF_SPEECH` handling also assumes two-pass semantics.
3. `force_to_speech_time=1000` (doc default `0`, doc-recommended `1000`) — prevents the first word of an utterance from being swallowed by premature VAD stops.

All three are covered by the E2E checklist.

## Escape hatch: `extra_request_params`

Anything this plugin does not model yet can be passed through directly — values merge into the `request` payload last:

```python
STT(
    ...,
    extra_request_params={
        "show_speech_rate": True,
    },
)
```

Use it for newly added service parameters without waiting for a plugin release. Because it merges last, an entry whose name matches a first-class option **overrides** it — you can also use it to try changed server semantics before a plugin release. If a parameter turns out to be broadly useful, it will graduate into a first-class option (see `DESIGN.md` for the graduation path).

## Capability coverage (unreleased)

Current matrix and evidence: [2026-09-09 capability validation](docs/capabilities-2026-09-09.md).

| Capability | Input | Output | Verification |
|---|---|---|---|
| Speaker separation | `enable_speaker_info: bool = False` | `utterances[].additions.speaker_id` → `SpeechData.speaker_id` | Live synthetic two-voice stream, IDs 0/1 |
| Language identification | `enable_lid: bool = False` | `utterances[].additions.lid_lang` → `SpeechData.language` | Live Mandarin/English; only `speech_mand` → `zh-CN`, `speech_en` → `en` |
| Diagnostics | No new option | `result.additions.log_id` + request_id in structured DEBUG logs | Live shape + offline log capture |
| Speech rate / volume / emotion / gender / age | Escape hatch | Not mapped | Deferred until samples and consumer contract |
| Full results | `result_type="full"` | Connection-local definite dedup exists since v0.1 | Live cumulative semantics not verified |
| Usage | No new option | Local sent-audio duration | Server `audio_info.duration` not used for billing |
| Corpus | First-class `corpus` | Shapes recognition at source | Request serialization tested; effectiveness not established |
| POI / music | Escape hatch possible | No dedicated integration | No current consumer |
| Legacy `ssd_version` | Escape hatch possible | Not required by current documented speaker path | Omitted in successful live ASR 2.0 probe |

`enable_speaker_info` and `enable_lid` also support `update_options`, using the
existing reconnect path. Both default to false and are omitted from default
requests. Escape-hatch values still override typed values.

Speaker labels are connection-local anonymous labels, not business identities.
Both features require `show_utterances=True` to expose their fields. Unknown,
missing, and unsupported language labels retain the configured language (or the
default `zh-CN`); English recognition does not establish a regional dialect.
No raw metadata interface or speaker-trait context hook is introduced yet.

## Combination hazards

The constructor warns when `enable_nonstream=False`, `show_utterances=False`,
or `result_type="full"` departs from the validated conversational profile.
Full mode already deduplicates definite utterances; it still needs live replay
validation before recommending it. Speaker/LID without utterances also warns.
These warnings do not reject provider-supported captioning use cases.

Frames from LiveKit are raw PCM: declaring a compressed/container format does
not encode them. Corpus changes reconnect; no per-turn config channel exists.
