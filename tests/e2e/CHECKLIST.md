# E2E 核对清单（个人 API key，周一执行）

前置：控制台开通豆包流式语音识别，拿个人 API key（`VOLCENGINE_API_KEY`）；
准备一段 16k 单声道 16bit wav（两人对话的音频最适合观察 speaker/空 final）。

## STT（`python stt_e2e.py audio.wav`）

1. **连通与事件流**：START_OF_SPEECH → INTERIM* → FINAL + END_OF_SPEECH 正常出现。
2. **默认值核对**（脚本会打印 request payload，对照 9.1 文档）：
   - [ ] enable_itn 文档默认 true，服务端实际行为
   - [ ] result_type=single 时多分句只回增量
   - [ ] force_to_speech_time=1000 无首句判停异常
3. **空 final**：静音段后观察 definite 且 text 为空 → 脚本末尾统计 "empty finals observed" ≥1 即验证修复路径真实存在。
4. **错误面**：故意用错 key 重跑 → 应立刻收到 APIStatusError 带服务端错误码，而不是挂到超时。
5. **两个 resource_id**：默认 seedasr 2.0 跑一遍 + `--resource-id volc.bigasr.sauc.duration` 跑一遍。
6. （可选）`extra_request_params={"enable_speaker_info": True, "ssd_version": "200"}` 观察返回是否带 speaker_id——同时回答公司侧 create_stt 的 ssd_version 断点问题。

## 结果记录

每项结论一行记入本文件底部（合并 PR 前的证据清单）；有出入的默认值回改 `stt.py` 并注明文档依据。
