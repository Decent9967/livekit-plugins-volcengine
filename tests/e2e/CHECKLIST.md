# E2E 核对清单（个人 API key，周一执行）

前置：控制台开通豆包流式语音识别，拿个人 API key（`VOLCENGINE_API_KEY`）；
准备一段 16k 单声道 16bit wav（两人对话的音频最适合观察 speaker/空 final）。

## STT（`python stt_e2e.py audio.wav`）

1. **连通与事件流**：START_OF_SPEECH → INTERIM* → FINAL + END_OF_SPEECH 正常出现。
2. **默认值核对**（脚本会打印 request payload，对照 9.1 文档）：
   - [ ] enable_itn 文档默认 true，服务端实际行为
   - [ ] result_type=single 时多分句只回增量
   - [ ] force_to_speech_time=1000 无首句判停异常
3. **空 final**：需要观察原始响应中的 definite 且 text 为空，再核对 END_OF_SPEECH；CLI 的普通事件输出无法证明原始空 final，不能以空字符串 FINAL 计数替代。
4. **错误面**：故意用错 key 重跑 → 应立刻收到 APIStatusError 带服务端错误码，而不是挂到超时。
5. **两个 resource_id**：默认 seedasr 2.0 跑一遍 + `--resource-id volc.bigasr.sauc.duration` 跑一遍。
6. （可选）`enable_speaker_info=True` 观察分句 additions 和事件是否带 speaker_id；ASR 2.0 已实测不需要旧隐藏参数 ssd_version。

## 长对话与异常场景（2026-09-07 精读 deepgram/gladia 后新增）

7. **闲置断连**：长静音（>60s 不说话）后继续说话，连接是否仍有效？若被服务端掐断，
   需评估 KeepAlive 机制（参考 deepgram 的 KeepAlive 消息模式）。
8. **限流退避**：触发限流（若可模拟）时观察错误码与表现。当前保留服务端错误码并交给
   锁定 SDK 的 APIStatusError/retry loop；未知的提供商业务码不等同于 HTTP 状态。
   没有真实证据前不宣称已验证限流策略，也不添加第二套重试循环。
9. **发送中途断线**：真实网络抖动下（可切代理模拟），验证发送侧错误被包装为
   可重试 APIConnectionError 且框架成功重连（本插件已有单测，E2E 复核真实环境）。
10. **计费口径**：观察响应中 audio_info.duration 与实际发送时长的关系——
    静音是否计费关系到是否需要 gladia 式的能量门控（发送侧剪静音省钱）。
11. **热词/上下文实测**：`corpus={"context": {"hotwords": [{"word": "某个专有名词"}]}}`
    （dict 会被自动序列化为官方要求的 JSON 字符串）+ 一段含该词的音频，
    对比开/关 corpus 的识别结果是否偏向热词写法；顺带用 `context_type=dialog_ctx`
    + 上一轮文本验证对话上下文注入（注意热词+上下文合计 100 token 上限）。
12. **分词与时间戳**：打印 SpeechEvent 的 `alternatives[0].words` 与 start_time/end_time，
    核对 words 确实随响应到达、毫秒→秒换算后时间值落在合理范围（ utterance
    start_time 应随音频推进而不是数千秒的离谱值）。
13. **响应形状存档**：把一段真实会话的原始响应 JSON（含 additions/audio_info/log_id
    的完整结构，脱敏后）存入 `tests/e2e/fixtures/`——这是响应侧漂移检测的基线：
    官方文档再更迭时，单测合成 payload 钉的是我们的映射，真实 fixture 钉的是服务端的形状。

## 结果记录

每项结论一行记入本文件底部（合并 PR 前的证据清单）；有出入的默认值回改 `stt.py` 并注明文档依据。

2026-09-09：已完成 ASR 2.0 默认生产参数、合成中文两句新旧对照、错误 key、65 秒持续发送静音后继续说话、真实响应脱敏存档。详见 [验证报告](../../docs/validation-0.1.0.md)。其余项目仍未验证，不能以此次通过代替。
