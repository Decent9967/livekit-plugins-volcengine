# v0.2.0 qualification — 2026-09-09

## Scope

Standalone plugin release, ASR 2.0 (`volc.seedasr.sauc.duration`), 16kHz mono
16-bit PCM, two-pass, 800ms endpoint. Default behavior remains unchanged.
This release does not upgrade the backend or publish to PyPI.

| Experiment | Observation | Decision |
|---|---|---|
| Single vs full, 9.055s shopping audio | Same two ordered finals and balanced speech boundaries | Full profile qualified for this sample; remove obsolete warning |
| Full with repeated speech, 19.61s | Four ordered finals, including legitimate repeated sentences | Existing connection-local dedup works; retain it |
| Speaker + Mandarin/English | Four finals with IDs 0/0/1/1 and languages zh-CN/zh-CN/en/en | Typed flags and standard SpeechData mapping |
| All metadata flags | Numeric strings and labels inside utterance additions | Normalize finite numbers, expose allowlisted fields in metadata.volcengine |
| Quarter-amplitude PCM | Volume approximately 76.47/74.75 → 65.42/64.00 provider dB | Direction verified; no calibrated SPL/dBFS claim |
| Faster synthesis (Rate=4) | Speech rate approximately 3.21/2.66 → 4.61 tokens/s; segmentation changed from two sentences to one | Measurement path verified, not an invariant word-count formula |
| Trait sensitivity | Same synthetic voice changes age ~43 → ~36 and emotion neutral → happy when accelerated | Estimates only; no personal-attribute accuracy claim |
| Plain / silent input duration | 9.055s → 9055ms, 3s silence → 3000ms | Duration includes silence; not speech-only time |
| Hot reconnect | Provider duration restarts per connection and latest response lags silence tail | Keep local transmitted-audio accounting; never sum response durations |
| Corpus control | 青蓝绮梦 / 云袖 | Two domain names mistranscribed without corpus |
| Identical audio + hotwords/dialog context | 青岚绮梦 / 云岫 | Both target spellings correct; one controlled example, not general accuracy proof |
| Candidate all flags + full | Two finals with speaker, LID and all observed metadata | Typed API confirmed against live service |

## Response contract

`SpeechData.metadata` is `None` when no supported value is present. Otherwise:

```python
{
    "volcengine": {
        "speech_rate": 3.21,  # provider tokens/s
        "volume": 76.47,  # provider dB; reference level not established
        "age": 43.14,  # provider estimate
        "gender": "female", "gender_score": 0.99,
        "emotion": "neutral", "emotion_score": 0.89,
        "emotion_degree": "weak", "emotion_degree_score": 0.99,
        "lid_lang": "speech_mand", "lid_lang_score": 0.98,
    }
}
```

Only supported keys are copied. Numeric strings become finite floats; nulls,
booleans, malformed numbers, NaN and infinity are omitted. Labels remain provider
strings, including future string values. Partial responses need not contain every
field. Interim, definite final and normal pending-final flush retain metadata.
There is no automatic insertion of traits into LLM context or identity binding.

## Usage and reconnect detail

Measured hot update: 20.11s audio pushed, 352000 + 289760 PCM bytes transmitted
(20.055s), and local usage events sum to 20.055s. The 55ms unsent partial chunk at
the configuration reconnect is discarded by the existing connection teardown.
Thus updates are disruptive connection changes, not seamless audio migration;
apply configuration before speech or at a deliberate idle boundary.

Provider latest durations were 9400ms and 9055ms for the two connections. The
first was not a terminal acknowledgement: response timing did not cover the
whole sent silence tail. Treating each duration as an increment, or using the
last response as a bill, would miscount. No accounting algorithm is changed.

## Reproducibility

Source: [official bidirectional API](https://docs.volcengine.com/docs/6561/2630027),
page updated September 1 and re-read September 9. Some acoustic descriptions were
blank in the rendered page; the dated repository snapshot supplies its stated
token/s and dB units. Actual values and shapes above come from live responses.

Synthetic inputs use Windows System.Speech Microsoft Huihui Desktop, 16kHz mono
16-bit output. Default rate 0, fast rate 4. Shopping text: “你好，请帮我推荐一件适合
秋天穿的外套。我喜欢蓝色，预算是五百元。” Corpus text: “请帮我查一下青岚绮梦这款
真丝围巾，还有云岫这款外套。” Quarter amplitude multiplies PCM samples by 0.25.
Repeat profile appends 1.5s silence then the same shopping PCM.

Each session sends 100ms frames in real time, ends input and drains responses;
SDK retries are disabled for measurement. `tests/fixtures/batch2-*.json` retain
effective options, PCM duration and complete provider response sequences, with
log_id/request_id/uid removed recursively. Replay tests exercise full/single/repeat
and real metadata results. They cannot measure future model accuracy.

Corpus treatment (same audio, separate connection):

```python
STT(corpus={"context": {
    "hotwords": [{"word": "青岚绮梦"}, {"word": "云岫"}],
    "context_type": "dialog_ctx",
    "context_data": [{"speaker": "bot", "text": "店内的青岚绮梦是真丝围巾，云岫是外套。"}],
}})
```

One initial baseline call returned APIStatusError before the probe recorded
status codes; its cause is unknown. The rerun and subsequent qualification calls
completed. This is not evidence of a provider SLA or absence of transient errors.

## Limits

No real-person overlap/diarization accuracy, dialect/singing recognition accuracy,
trait accuracy, ASR 1.0/concurrent resource, image context, corpus ablation or
billing reconciliation claim. Speaker IDs remain connection-local. Full-mode
qualification covers these fixtures, not every possible provider revision pattern.

Independent code review found no blocking issue; its pending-final assertion and
real-metadata replay suggestions were added. Local suite: 96 tests; release CI
also runs Python 3.10, 3.11, 3.12 and 3.13.
