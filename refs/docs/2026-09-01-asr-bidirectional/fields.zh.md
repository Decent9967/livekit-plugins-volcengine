# 豆包大模型流式语音识别 · 双向流式 WebSocket（文档快照）

- 来源：<https://docs.volcengine.com/docs/6561/2630027?lang=zh>
- 快照日期：2026-09-01 版本（用户于 2026-09-07 全文粘贴存档）
- 性质：字段清单快照，用于与未来版本 diff。**内容为火山公开文档的摘录整理，版权属火山引擎，不得从本仓库再分发**（本目录已 gitignore）。

## 端点与鉴权

- `POST wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async`
- `X-Api-Key`（必选；支持旧版控制台鉴权）
- `X-Api-Resource-Id`（必选）：
  - 2.0（推荐）：`volc.seedasr.sauc.duration`（小时版）/ `volc.seedasr.sauc.concurrent`（并发版）
  - 1.0：`volc.bigasr.sauc.duration` / `volc.bigasr.sauc.concurrent`
- `X-Api-Request-Id`（必选，推荐 UUID）

## 请求体 audio（dict，必选）

| 字段 | 类型 | 必选 | 说明 |
|---|---|---|---|
| format | string | ✅ | wav/mp3/ogg/pcm/spx/amr/aac/m4a |
| codec | string | | raw（默认，pcm）/ opus |
| rate | int | | 默认 16000 |
| bits | int | | 默认 16 |
| channel | int | | 默认 1；可选 2（stereo） |

## 请求体 request

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| model_name | string | 必选 | 目前仅支持 `bigmodel` |
| enable_nonstream | bool | false | 二遍识别：VAD 分句后用非流式模型二次识别，仅二遍结果携带 `definite:true`；开启后自动启用 VAD（默认静音 800ms 判句，`end_window_size` 可调） |
| enable_speaker_info | bool | false | 说话人聚类分离；推荐搭配 2.0；需同时开启 show_utterances |
| enable_itn | bool | **true** | 文本规范化（口语→书面，如 "一九七零年"→"1970 年"） |
| enable_punc | bool | true | 标点 |
| enable_ddc | bool | false | 语义顺滑（去停顿/语气/重复词） |
| output_zh_variant | string | | traditional / tw / hk（简→繁变体） |
| show_utterances | bool | false | 输出分句/分词/说话人/停顿信息 |
| show_speech_rate | bool | false | 分句 additions 带语速（token/s）；自动启用 VAD |
| show_volume | bool | false | 分句 additions 带音量（dB）；自动启用 VAD |
| enable_lid | bool | false | 中英+方言识别（含唱歌场景），additions 返回语种标签 |
| enable_emotion_detection | bool | False | 情绪标签（angry/happy/neutral/sad/surprise） |
| enable_gender_detection | bool | False | 性别标签（male/female） |
| enable_age_detection | bool | False | 年龄估算（字符串浮点数） |
| result_type | string | **full** | full=全量返回 / single=增量返回 |
| enable_accelerate_text | bool | false | 首字返回加速（可能降低首字准确率） |
| accelerate_score | int | 0 | 加速率，需同时开启 enable_accelerate_text |
| vad_segment_duration | int | 3000 | 语义分句最大静音 ms；仅影响分句不影响 definite；配置了 end_window_size 时**不生效** |
| end_window_size | int | 800 | VAD 判停静音阈值 ms，范围 [300,5000]，推荐 [800,1000] |
| force_to_speech_time | int | **0**（推荐 1000） | 起始段强制按有声处理时长 ms |
| sensitive_words_filter | string | | JSON 字符串：system_reserved_filter(bool)/filter_with_empty(list)/filter_with_signed(list) |
| enable_poi_fc | bool | false | POI Function Call（地图领域推荐词）；需 enable_nonstream=true |
| enable_music_fc | bool | false | Music Function Call；需 enable_nonstream=true |
| corpus | object | | 语境词典：boosting_table_name/id、correct_table_name/id、regex_correct_table_name/id、context、hotwords；上下文+热词合计上限 100 tokens |
| corpus.context | string | | 序列化为 JSON 传入：hotwords[{word}]、context_type:"dialog_ctx"、context_data[{speaker,text}]、image_url（仅 2.0，≤1 张、≤500KB、jpeg/jpg/png；需 enable_nonstream） |

## 响应

| 字段 | 说明 |
|---|---|
| code | 0 成功，非 0 失败 |
| event | 会话事件类型 |
| is_last_package | 是否最后一个响应包 |
| payload_sequence / payload_size / payload_msg | 序号 / 字节数 / 数据主体 |
| audio_info.duration | 音频时长 ms |
| additions.log_id | 服务端 logid（排障用） |
| result (list) | 识别结果：text、confidence、additions |
| utterances[] | definite(bool，二遍结果为 true)、text、start_time/end_time(ms)、additions{fixed_prefix_result, source}、speaker_id（需 enable_speaker_info）、words[] |

## 与本实现的对照注记

- 本插件 STT 默认：`enable_itn=True`（同文档默认）、`result_type="single"`（**不同于**文档默认 full，面向增量上屏）、`force_to_speech_time=1000`（文档推荐值）、`vad_segment_duration` 不显式发（文档：配置 end_window_size 时不生效）。
- 隐藏参数（文档未列、旧文档 1354869 有）：`ssd_version="200"`，说话人分离疑似需要；经 `extra_request_params` 透传，待 E2E 实证。
