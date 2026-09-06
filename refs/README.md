# refs/ · 官方参考资料存档

> **免责声明**：本目录收集自互联网公开内容（厂商公开文档页与官方公开 demo 附件），
> 仅用于协议实现比对与开发参考，版权归原作者（火山引擎）所有；如有侵权，请联系删除。

本插件的协议事实（帧格式、常量、参数语义）追溯到这里存档的公开来源。
官方更新时按底部流程比对。

## 来源登记

| 来源 | 日期 | 获取途径 | SHA256 |
|---|---|---|---|
| 官方 Python demo（解压版） | 2026-09-06 下载 | [文档附件 sauc_python.zip](https://portal.volccdn.com/obj/volcfe/cloud-universal-doc/upload_084f2effab285cf82e5196388e0bd354.zip) | 附件 URL 含内容指纹，更新时自动可检出 |
| 双向流式 ASR 文档 | 2026-09-01 版 | <https://docs.volcengine.com/docs/6561/2630027> | 快照见 `docs/2026-09-01-asr-bidirectional/` |

## 目录

```
refs/
├── README.md
├── vendor/
│   └── sauc_python/         ← 解压（protocol.py 为协议参照）
└── docs/
    └── 2026-09-01-asr-bidirectional/
        ├── full.zh.md           ← 渲染全文（官方「复制全文」导出，可 git diff）
        ├── fields.zh.md         ← 字段表快照（中文整理版）
        └── fields.en.md         ← 字段表快照（英文等价译本）
```

> 说明：`full.zh.md` 通过官方页面「复制全文」按钮获取（正文由 JS 动态加载，
> 静态抓取拿不到，用浏览器自动化点击后从剪贴板读取）。
> 版权归火山引擎，收集自公开内容，仅用于开发比对。

## 官方更新时的比对流程

1. **检测**：demo zip 的 URL 内嵌内容指纹（`upload_084f2eff…` 段），链接变了即内容变了；文档页看更新时间。
2. **抓取**：用浏览器自动化点击页面「复制全文」按钮，从剪贴板读取官方结构化导出，覆盖 `docs/2026-09-01-asr-bidirectional/full.zh.md`。
3. **diff**：`git diff refs/` 逐行看官方改了什么（对照字段表分「新增字段 / 默认值变更 / 语义修订」三类记录）。
4. **提交**：`git commit -m "refs: 官方更新 2026-XX-XX（一句话）"`——提交历史即官方变更日志。
5. **落地**：影响实现的开 issue、改代码、重跑单测 + E2E（`tests/e2e/CHECKLIST.md`）。
