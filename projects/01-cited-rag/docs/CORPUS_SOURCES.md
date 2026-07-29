# 官方 HTML 语料来源

- 状态：`acquired_and_validated`
- 批准日期：`2026-07-28`
- 精确清单：`data/sources/source-catalog.json`

## 范围

- Python `3.14.6` 简体中文文档：17 个教程页面、4 个库页面、1 个“3.14 有什么新变化”页面。
- Python `3.13.14` 简体中文文档：`argparse`、`pathlib` 和“3.13 有什么新变化”。
- 正文语料共 25 页。
- 另保存 Python `3.14` 官方许可页面 1 页作为证据，不进入检索语料。

## 许可

Python 官方许可页面说明，Python 软件和文档使用 Python Software Foundation License Version 2。自 Python `3.8.6` 起，文档中的示例、配方和代码片段还可按照 Zero-Clause BSD License 使用。

- 许可页面：<https://docs.python.org/zh-cn/3.14/license.html>
- Manifest 中保留许可名称和许可 URL。
- 本地许可 HTML 保存到 `data/sources/license/`，但不进入索引。

## 获取和保存边界

- 只允许清单中列出的 `https://docs.python.org` URL。
- 不递归跟随页面链接，不下载 CSS、JavaScript、图片或字体。
- 只接受仍位于 `docs.python.org` 的 HTTPS 重定向。
- 只接受 `text/html`，单页上限 10 MiB。
- 保存最终 URL、UTC 获取时间、实际字节数、原始字节 SHA-256 和观察到的 `h1`。
- 原始 HTML 保存到 `data/sources/html/{documentation_release}/`。
- 原始 HTML 和许可快照是本地可重建数据，暂不提交 Git。
- `source-catalog.json`、获取报告、最终 `manifest.json` 和本说明提交 Git。

## 标题确认

下载工具只机械提取真实 HTML 的首个 `h1`，不调用模型。生成正式 Manifest 前，应检查提取标题和精确发布版，再把已确认标题写入 `expected_title`。

## 本次获取结果

- 获取日期：`2026-07-28`
- 正文 HTML：25份
- 许可证据 HTML：1份
- 总字节数：3,581,318
- 全部页面最终 URL 与批准 URL 一致。
- 全部页面为 `text/html`，均有非空 `h1`。
- 精确发布版：Python `3.14.6`、Python `3.13.14`。
- Manifest：`data/sources/manifest.json`
- Manifest SHA-256：`60258d7589162244cce9dc24ef79a26fe7f1cee1d05af5692f228d614947ae43`
- 离线真实导入：25份文档全部通过，共5003个内容 Block。
- 使用同一活动 Manifest 重复导入返回 `UNCHANGED`，且真实文件被重新读取验证。
- Corpus ID：`5386ccee-bb5f-5417-b70a-33395abe9669`

真实页面的 canonical URL 使用 Python 官方语言无关 `/3/` 路径。导入器只接受与简体中文来源 URL 文档后缀完全对应的官方 canonical，不接受任意同域页面。
