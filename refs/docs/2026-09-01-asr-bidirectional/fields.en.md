# Doubao Streaming ASR · Bidirectional WebSocket (document snapshot)

- Source: <https://docs.volcengine.com/docs/6561/2630027?lang=zh>
- Snapshot: 2026-09-01 revision (pasted in full by the user on 2026-09-07; Chinese original in the `.zh.md` sibling file)
- Note: English version is a working translation for non-Chinese readers; **the Chinese original is authoritative**. Content belongs to Volcengine; collected from publicly available material.

> ⚠️ This snapshot is incomplete: it was captured via manual copy of the field
> tables. The full official text (including endpoint description prose and any
> embedded examples) lives on the live page and in the downloadable PDF. The
> official demo archives (`refs/vendor/sauc_python.zip`, `sauc_go.zip`) cover
> the wire-protocol facts.

## Endpoint & auth

- `POST wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async`
- `X-Api-Key` (required; legacy console auth also supported)
- `X-Api-Resource-Id` (required):
  - 2.0 (recommended): `volc.seedasr.sauc.duration` (hourly) / `volc.seedasr.sauc.concurrent` (concurrency)
  - 1.0: `volc.bigasr.sauc.duration` / `volc.bigasr.sauc.concurrent`
- `X-Api-Request-Id` (required, UUID recommended)

## Request body — audio (dict, required)

| Field | Type | Req | Notes |
|---|---|---|---|
| format | string | ✅ | wav/mp3/ogg/pcm/spx/amr/aac/m4a |
| codec | string | | raw (default, pcm) / opus |
| rate | int | | default 16000 |
| bits | int | | default 16 |
| channel | int | | default 1; 2 = stereo |

## Request body — request

| Field | Type | Default | Notes |
|---|---|---|---|
| model_name | string | required | currently only `bigmodel` |
| enable_nonstream | bool | false | two-pass: VAD segmentation + second non-streaming pass; only second-pass results carry `definite:true`; enabling auto-enables VAD (800 ms default, tunable via `end_window_size`) |
| enable_speaker_info | bool | false | speaker clustering/diarization; recommended with 2.0; requires show_utterances |
| enable_itn | bool | **true** | inverse text normalization ("1970年" style) |
| enable_punc | bool | true | punctuation |
| enable_ddc | bool | false | semantic smoothness (removes fillers/repeats) |
| output_zh_variant | string | | traditional / tw / hk |
| show_utterances | bool | false | sentence/word/speaker/pause info |
| show_speech_rate | bool | false | speech rate (token/s) in utterance additions; auto-enables VAD |
| show_volume | bool | false | volume (dB) in utterance additions; auto-enables VAD |
| enable_lid | bool | false | language/dialect ID incl. singing tags |
| enable_emotion_detection | bool | false | emotion tags (angry/happy/neutral/sad/surprise) |
| enable_gender_detection | bool | false | gender tag (male/female) |
| enable_age_detection | bool | false | age estimate (string float) |
| result_type | string | **full** | full = cumulative; single = incremental |
| enable_accelerate_text | bool | false | faster first token, may reduce accuracy |
| accelerate_score | int | 0 | acceleration rate; requires enable_accelerate_text |
| vad_segment_duration | int | 3000 | max silence for semantic segmentation; no effect while `end_window_size` is set |
| end_window_size | int | 800 | VAD silence threshold ms, range [300,5000], recommended [800,1000] |
| force_to_speech_time | int | **0** (recommended 1000) | leading audio treated as speech to avoid premature stops |
| sensitive_words_filter | string | | JSON string: system_reserved_filter(bool) / filter_with_empty(list) / filter_with_signed(list) |
| enable_poi_fc | bool | false | POI function call; requires enable_nonstream=true |
| enable_music_fc | bool | false | music function call; requires enable_nonstream=true |
| corpus | object | | boosting_table_name/id, correct_table_name/id, regex_correct_table_name/id, context, hotwords; context+hotwords capped at 100 tokens |
| corpus.context | string | | JSON-stringified: hotwords[{word}], context_type:"dialog_ctx", context_data[{speaker,text}], image_url (2.0 only, ≤1 image ≤500KB jpeg/jpg/png; requires enable_nonstream) |

## Response

| Field | Notes |
|---|---|
| code | 0 = success |
| event | session event type |
| is_last_package | true = all results returned |
| payload_sequence / payload_size / payload_msg | sequence / byte size / body |
| audio_info.duration | audio duration ms |
| additions.log_id | server log id for support |
| result (list) | text, confidence, additions |
| utterances[] | definite(bool), text, start_time/end_time (ms), additions{fixed_prefix_result, source}, speaker_id (needs enable_speaker_info), words[] |

## Notes vs this plugin's implementation

- Plugin STT defaults: `enable_itn=True` (matches doc default), `result_type="single"` (**differs from** doc default `full` — incremental output suits live agents), `force_to_speech_time=1000` (doc-recommended), `vad_segment_duration` not sent explicitly (doc: ignored when `end_window_size` is set).
- Hidden parameter (not listed on this page; documented on legacy page 1354869): `ssd_version="200"` — speaker separation likely requires it; passed via `extra_request_params`, pending E2E verification.
