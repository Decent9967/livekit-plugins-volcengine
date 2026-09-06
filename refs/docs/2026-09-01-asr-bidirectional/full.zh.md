# 双向流式语音识别 WebSocket · 官方「复制全文」导出（结构化）

- 来源: https://docs.volcengine.com/docs/6561/2630027?lang=zh
- 文档版本: 2026-09-01 | 快照日期: 2026-09-07
- 提取方式: 官方页面「复制全文」按钮 → 剪贴板（站点自有结构化导出，含标题/字段/代码块）
- 性质: 收集自互联网公开内容，仅用于开发比对，版权归原作者（火山引擎）所有
- 配套: 字段表整理版见同目录 .zh.md / .en.md；官方 demo 见 ../vendor/

---

支持音频流式输入，实时返回识别结果，实现边说边出字。识别延迟优于单向流式接口，适用于实时会议字幕、直播字幕、智能外呼等低延迟场景

&nbsp;

> 运行依赖文件

> 
<Tabs>
<Tab zoneid="ZdWDeQZL" title="Python">
<TabTitle>Python</TabTitle>

&nbsp;

<Attachment link="https://portal.volccdn.com/obj/volcfe/cloud-universal-doc/upload_084f2effab285cf82e5196388e0bd354.zip" name="sauc_python.zip">sauc_python.zip</Attachment>



</Tab>
<Tab zoneid="cMxx2BqQ" title="Go">
<TabTitle>Go</TabTitle>

&nbsp;

<Attachment link="https://portal.volccdn.com/obj/volcfe/cloud-universal-doc/upload_25e3ec23373a78508cf36cb446a4141f.zip" name="sauc_go.zip">sauc_go.zip</Attachment>



</Tab>
</Tabs>




---



<span data-label="purple">POST</span> wss://[openspeech.bytedance.com/api/v3/sauc/bigmodel_async](http://openspeech.bytedance.com/api/v3/sauc/bigmodel_async)

&nbsp;


<span id="ULAS3Id9"></span>
### 请求头


**X\-Api\-Key ** `string` <span data-api-tag="require|1RbFw3">必选</span>

API Key 可从 [控制台>API Key管理](https://console.volcengine.com/speech/new/setting/apikeys?projectName=default.) 获取

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">同时支持<a href="https://console.volcengine.com/speech/service/10035">旧版控制台</a>的鉴权方式，详见：<a href="https://docs.volcengine.com/docs/6561/2534847?lang=zh">旧版控制台鉴权参考示例</a></div>




**X\-Api\-Resource\-Id ** `string` <span data-api-tag="require|W2vM70">必选</span>

指定请求的模型版本，可选值：


* 豆包流式语音识别模型2.0 <span data-label="purple">推荐</span>

   * 小时版：`volc.seedasr.sauc.duration`

   * 并发版：`volc.seedasr.sauc.concurrent`

* 豆包流式语音识别模型1.0

   * 小时版：`volc.bigasr.sauc.duration` 

   * 并发版：`volc.bigasr.sauc.concurrent `



**X\-Api\-Request\-Id ** `string` <span data-api-tag="require|W2vM70">必选</span>

提交和查询任务的任务ID，推荐传入随机生成的UUID




<span id="OG7QrhRG"></span>
### 请求体


**audio ** `dict` <span data-api-tag="require|WnVo1B">必选</span>


**format ** `string` <span data-api-tag="require|7sHXWE">必选</span>

指定音频格式。

可选值：`wav` / `mp3` / `ogg `/ `pcm` /` spx` / `amr` /` aac` / `m4a`



**codec** `string`

指定音频编码格式，默认为raw（pcm）

可选值：`raw` / `opus`



**rate** `int`

指定音频采样率，默认值为 `16000`



**bits** `int`

指定音频采样点位数，默认值为`16`



**channel** `int`

指定音频声道数，默认值为 `1`

可选值：

`1`：mono

`2`：stereo




**request** `object`


**model_name** `string` <span data-api-tag="require|tXLKeG">必选</span>

指定模型名称，目前仅支持 `bigmodel` 



**enable_nonstream ** `bool`

开启**二遍识别模式，** 默认为`false`。开启后，在双向流式实时识别的基础上，对每个分句额外使用非流式模型（nostream）进行二次识别，提升分句的最终准确率。既满足实时上屏的 “快”, 又保证最终结果的 “准”

**开启后的行为:** 


* 自动启用语音活动检测（VAD）进行分句，默认静音时长达到 800ms 判定为一句结束，可通过 `end_window_size `参数调整该阈值

* 每次 VAD 检测到分句结束时，使用非流式模型对该分句音频重新识别

* 仅非流式模型的二次识别结果会携带` "definite": true `字段，用于标记该分句为最终确定结果



**enable_speaker_info** `bool`

启用说话人分离参数，默认为`false`。推荐搭配**豆包流式语音识别模型 2.0** 使用

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">开启后需启用<code>show_utterances</code>参数，才能获取到说话人分离结果</div>




**enable_itn** `bool`

启用将语音识别结果转换为规范的书面格式，默认为`true`

开启后，系统会将语音里口语化的数字、金额及日期等自动转成阿拉伯数字和符号形式，使文本更简洁、更易读

效果示例:


* "一九七零年" → "1970 年"

* "一百二十三美元" → "$123"



**enable_punc** `bool`

启用标点，默认为`true`

开启后，系统会在识别结果中添加逗号、句号、问号等标点符号，提升文本可读性



**enable_ddc** `bool`

启用语义顺滑，默认为 `false`

开启后，系统会删除或修正识别结果中的停顿词、语气词、语义重复词等不流畅内容，让文本更连贯、更易读



**output_zh_variant ** `string`

将识别结果输出为繁体中文。

可选值：


* `traditional`:简体 → 繁体（大陆）

* `tw`：简体 → 台湾正体

* `hk`：简体 → 香港繁体



**show_utterances** `bool`

启用输出分句、分词、说话人及语音停顿信息，默认为`false`



**show_speech_rate** `bool`

启用分句信息携带语速，默认为`false`

开启后，系统将在分句 `additions` 中返回语速信息，单位为 token/s

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">开启此参数后，会自动启用语音活动检测（VAD）进行分句，默认静音时长达到 800ms 判定为一句结束，可通过 <code>end_window_size </code>参数调整该阈值</div>




**show_volume** `bool`

启用分句信息携带音量，默认 `false`

开启后，系统将在分句 `additions` 中返回音量信息，单位为dB

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">开启此参数后，会自动启用语音活动检测（VAD）进行分句，默认静音时长达到 800ms 判定为一句结束，可通过 <code>end_window_size </code>参数调整该阈值</div>




**enable_lid** `bool`

启用中英文及方言识别，默认 `false`

支持识别以下语种：中文、英文、上海话、闽南话、四川话、陕西话、粤语

开启后，系统将在 `additions` 中返回语种/场景标签，取值如下：


* `singing_en`：英文唱歌

* `singing_mand`：普通话唱歌

* `singing_dia_cant`：粤语唱歌

* `speech_en`：英文说话

* `speech_mand`：普通话说话

* `speech_dia_nan`：闽南语

* `speech_dia_wuu`：吴语（含上海话）

* `speech_dia_cant`：粤语说话

* `speech_dia_xina`：西南官话（含四川话）

* `speech_dia_zgyu`：中原官话（含陕西话）

* `other_langs`：其它语种（其它语种人声）

* `others`：检测不出（非语义人声和非人声）

* 返回为空则代表无法判断（例如传入音频过短等）


<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">开启此参数后，会自动启用语音活动检测（VAD）进行分句，默认静音时长达到 800ms 判定为一句结束，可通过 <code>end_window_size </code>参数调整该阈值</div>




**enable_emotion_detection** `bool`

启用情绪检测，默认为 `False`

开启后，系统将在分句`additions`中返回对应的情绪标签。支持的情绪标签如下：


* `angry`：表示情绪为生气

* `happy`：表示情绪为开心

* `neutral`：表示情绪为平静或中性

* `sad`：表示情绪为悲伤

* `surprise`：表示情绪为惊讶


<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">开启此参数后，会自动启用语音活动检测（VAD）进行分句，默认静音时长达到 800ms 判定为一句结束，可通过 <code>end_window_size </code>参数调整该阈值</div>




**enable_gender_detection** `bool`

启用性别检测，默认为 `False`

开启后，系统将在分句`additions`中返回性别标签（male/female）

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">开启此参数后，会自动启用语音活动检测（VAD）进行分句，默认静音时长达到 800ms 判定为一句结束，可通过 <code>end_window_size </code>参数调整该阈值</div>




**enable_age_detection**`bool`

启用年龄检测，默认为`False`

开启后，系统将在分句`additions`中返回说话人的年龄（age），返回值为字符串类型的浮点数

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">年龄检测是模型基于语音特征对说话人年龄做出的估算，结果仅供参考。实际准确率受录音质量、说话语速、及口音等多种因素影响</div>




**result_type ** `string`

指定识别结果的返回方式，默认值为`full`

可选值：


* `full`：全量返回

* `single`：增量结果返回，即不返回之前分句的结果



**enable_accelerate_text ** `bool`

启用首字返回加速，默认值为`false`。

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">启用后将尽量加速首字返回，但同时可能会降低首字准确率，请根据实际场景需要谨慎选择</div>




**accelerate_score** `int`

指定首字返回加速率，默认值为`0`，表示不加速。设置的值越大，首字出字越快。

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">该参数需同时开启<code>enable_accelerate_text</code>参数</div>




**vad_segment_duration** `int`

指定语义分句的最大静音阈值，默认值为3000，单位为ms。当静音时长超过该值时，识别结果在此处分句

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>



* <div data-tips="true" data-tips-type="default">此参数仅影响语义分句，不触发判停，不改变 <code>definite </code>返回位置</div>


* <div data-tips="true" data-tips-type="default">若同时配置了<code>end_window_size</code>，此参数不生效</div>




**end_window_size** `int`

指定语音活动检测 (VAD) 的静音判停阈值，默认值为 `800`，单位 ms。当检测到的连续静音时长达到该值时，则判定一句话结束并触发分句。

取值范围：`[300,5000] `

推荐值：`[800,1000]`



**force_to_speech_time ** `int`

设置音频流起始阶段强制按有声处理的时长，默认值为`0`，单位为 ms

该参数用于规避音频起始处因静音或弱音导致的过早判停或无法判起问题。设定时长内即使输入为静音也不触发 VAD 判停，超时后恢复正常判停逻辑

推荐值：`1000`



**sensitive_words_filter** `string`

启用敏感词过滤功能。开启后，可对识别结果中的敏感词做屏蔽或替换处理

示例

```Bash
"sensitive_words_filter":"{\"system_reserved_filter\":true,\"filter_with_empty\":[\"敏感词\"],\"filter_with_signed\":[\"敏感词\"]}"
```



**system_reserved_filter ** `bool`

启用系统内置敏感词库，默认为`false`，启用后，命中的系统敏感词会被替换为 `*`



**filter_with_empty ** `string`

设置需替换为空字符串的自定义敏感词列表



**filter_with_signed ** `string`

设置需替换为 `*` 的自定义敏感词列表




**enable_poi_fc** `bool`

启用 POI Function Call，默认为`false`，启用后可调用专业的地图领域推荐词服务辅助识别，提高识别准确率

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">使用该能力时，需要将<code>enable_nonstream</code>设置为<code>true</code></div>


示例：

```SQL
"request": {
    "enable_poi_fc": true,
    "corpus": {
        "context": "{\"loc_info\":{\"city_name\":\"北京市\"}}"
    }
}
```




**enable_music_fc** `bool`

启用 Music Function Call，默认为`false`，开启后，对于语音识别困难的词语，能调用专业的音乐领域推荐词服务辅助识别

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">使用该能力时，需要将<code>enable_nonstream</code>设置为<code>true</code></div>




**corpus** `object`

配置语境词典，可自定义配置热词、替换词和上下文信息，配置后可提高特定语境下的词语识别准确率

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>



* <div data-tips="true" data-tips-type="default">上下文与热词（含直传热词与热词表热词）最大支持上传100 tokens。当上传的总长度超过 100 tokens 时，系统按传入顺序从前向后截断，仅前 100 tokens 内的内容生效；开启<code>enable_nonstream</code>参数时，支持情况请参考<a href="https://docs.volcengine.com/docs/6561/2628951?lang=zh">单向流式语音识别接口</a>文档中<code>corpus</code>对应的描述</div>


* <div data-tips="true" data-tips-type="default">热词属于提示性参数，用于引导模型优先识别特定词汇，但并非强制约束。模型会在识别过程中优先考虑热词，但受语音清晰度、语境等多种因素影响，不保证所有热词都能 100% 正确转写</div>


* <div data-tips="true" data-tips-type="default">热词的效果和选词、数量、格式都有关，为达到最佳效果建议根据<a href="https://docs.volcengine.com/docs/6561/2604976?lang=zh">热词与上下文最佳实践</a>配置热词和上下文信息</div>




**boosting_table_name ** `string`

热词词表名称，可在[控制台>自学习平台](https://console.volcengine.com/speech/new/hot-word?projectName=default)配置热词后获取



**boosting_table_id ** `string`

热词词表id，可在[控制台>自学习平台](https://console.volcengine.com/speech/new/hot-word?projectName=default)配置热词后获取

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">若传入的<code>boosting_table_name</code>和<code>boosting_table_id</code>对应的热词词表不一致，则以<code>boosting_table_id</code>为准</div>




**correct_table_name ** `string`

替换词词表名称，可在[控制台>自学习平台](https://console.volcengine.com/speech/new/correct-word?projectName=default)配置替换词后获取。配置后，可将模型识别出的特定词汇替换为目标词汇



**correct_table_id ** `string`

替换词词表id，可在[控制台>自学习平台](https://console.volcengine.com/speech/new/correct-word?projectName=default)配置替换词后获取。配置后，可将模型识别出的特定词汇替换为目标词汇

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>


<div data-tips="true" data-tips-type="default">若传入的<code>correct_table_name</code>和<code>correct_table_id</code>对应的热词词表不一致，则以<code>correct_table_id</code>为准</div>




**regex_correct_table_name**`string`

正则替换词表名称，可在[控制台>自学习平台](https://console.volcengine.com/speech/new/correct-word?projectName=default)配置正则替换词后获取。相较于替换词的精确匹配替换，正则替换词适合批量格式转换（如日期格式统一、符号标准化）、模糊模式匹配等复杂场景



**regex_correct_table_id ** `string`

正则替换词表id，可在[控制台>自学习平台](https://console.volcengine.com/speech/new/correct-word?projectName=default)配置正则替换词后获取。相较于替换词的精确匹配替换，正则替换词适合批量格式转换（如日期格式统一、符号标准化）、模糊模式匹配等复杂场景



**context ** `string`

上下文功能。在识别请求中传入辅助上下文信息，帮助模型结合语境提升识别准确率。支持传入热词、对话历史、场景描述等多种类型的上下文信息

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>



* <div data-tips="true" data-tips-type="default">实际传参时<strong> </strong><strong><code>context</code></strong><strong> 需序列化为 JSON 字符串传入</strong>，如：<code>"context": "{\"hotwords\":[{\"word\":\"自定义热词A\"},,\"context_type\":\"dialog_ctx\",\"context_data\":[{\"speaker\":\"bot\",\"text\":\"最近一轮助手的回答\"}"</code></div>


* <div data-tips="true" data-tips-type="default">识别效果与热词的选词策略、上下文信息有关，为达到最佳效果建议根据<a href="https://docs.volcengine.com/docs/6561/2604976?lang=zh">热词与上下文最佳实践</a>配置热词和上下文信息</div>



**示例：** 

```Python
{
  "hotwords": [
    { "word": "自定义热词A" },
    { "word": "自定义热词B" },
    { "word": "自定义热词C" }
  ],
  "context_type": "dialog_ctx",
  "context_data": [
    {
      "speaker": "user",
      "text": "你能帮我查一下资料吗？"
    },
    {
      "speaker": "bot",
      "text": "当然可以，请问您需要查什么资料？"
    },
    {
      "speaker": "user",
      "text": "帮我查一下最新的汽车资讯。"
    },
    {
      "speaker": "bot",
      "text": "好的，正在为您查找相关的汽车资讯。"
    }
  ]
}
```



**Hotwords**`string`

热词列表直传，用于提升指定词汇的识别准确率。


**word**`string`

热词内容

<div data-tips="true" data-tips-type="default" data-tips-is-title="true">说明</div>



* <div data-tips="true" data-tips-type="default">上下文与热词（含直传热词与热词表热词）最大支持上传100 tokens。当上传的总长度超过 100 tokens 时，系统按传入顺序从前向后截断，仅前 100 tokens 内的内容生效；开启<code>enable_nonstream</code>参数时，支持情况请参考<a href="https://docs.volcengine.com/docs/6561/2628951?lang=zh">单向流式语音识别接口</a>文档中<code>corpus</code>对应的描述</div>


* <div data-tips="true" data-tips-type="default">热词属于提示性参数，用于引导模型优先识别特定词汇，但并非强制约束。模型会在识别过程中优先考虑热词，但受语音清晰度、语境等多种因素影响，不保证所有热词都能 100% 正确转写</div>


* <div data-tips="true" data-tips-type="default">识别效果与热词的选词策略、上下文信息有关，为达到最佳效果建议根据<a href="https://docs.volcengine.com/docs/6561/2604976?lang=zh">热词与上下文最佳实践</a>配置热词和上下文信息</div>





**context_type** `string`

上下文类型，目前仅支持`dialog_ctx`



**context_data** `object`

上下文数据列表，用于传入历史对话等语境信息，需同时配置`context_type`


**text ** `string`

历史对话文本，帮助模型理解语境，提升识别准确率



**image_url**`string`

图片 URL，用于提供视觉上下文，辅助理解语音内容

<div data-tips="true" data-tips-type="default">说明</div>



* <div data-tips="true" data-tips-type="default">仅当开启<code>enable_nonstream</code>参数时，支持上传图片 URL</div>


* <div data-tips="true" data-tips-type="default">仅豆包流式语音识别模型 2.0 支持图片输入。当前限制：最多传入 1 张图片，单张大小不超过 500 KB，支持格式为<code> jpeg </code>/<code>jpg</code>/<code>png</code></div>









<span id="pF6mxalL"></span>
### 响应


**code ** `int`

请求状态码。0 表示识别成功，非 0 表示识别失败



**event** `int`

会话事件类型标识



**is_last_package ** `bool`

是否为最后一个响应包。`true` 表示识别结果已全部返回



**payload_sequence ** `int`

响应数据包的序号



**payload_size ** `int`

响应数据 payload 的字节大小



**payload_msg ** `object`

响应数据主体，包含音频信息与识别结果


**audio_info ** `object`

音频相关信息


**duration ** `int`

音频时长，单位为毫秒（ms）




**result ** `list`

识别结果，识别成功后返回


**additions ** `object`


**log_id** `string`

服务端返回的 logid，方便定位问题




**text ** `string`

音频识别结果文本，识别成功后返回



**utterances ** `list`

语音分句信息。满足以下条件时返回：


* 请求参数`show_utterances`设置为`true`

* 识别成功



**definite ** `bool`

当前分句结果是否为最终确定结果。`true` 表示该分句不再变化



**additions ** `string`


**fixed_prefix_result ** `string`

已确定的前缀识别结果



**source ** `string`

分句结果来源



**speaker_id ** `string`

说话人 ID。开启说话人分离 `enable_speaker_info=true`后返回




**text**`string`

分句文本内容



**end_time ** `int`

分句结束时间戳（毫秒）



**start_time**`int`

分句起始时间戳（毫秒）



**words** `list`

分词信息列表。请求参数`show_utterances`设置为`true`且识别成功时返回


**start_time ** `int`

起始时间（毫秒）



**end_time ** `int`

结束时间（毫秒）



**text ** `string`

语音文本内容。满足以下条件时返回：


* 请求参数`show_utterances`设置为`true`

* 识别成功







 &nbsp;

&nbsp;
