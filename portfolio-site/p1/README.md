# P1静态证据页

V2-E2B公开静态证据页：<https://rorinhoon-bot.github.io/ai-application-portfolio/>。

边界：

- 录制证据，非实时推理。
- 不接收任意问题，不连接FastAPI、Qdrant或MiMo。
- 不含远程JavaScript、字体、分析、追踪、表单或iframe。
- 指标与案例由`projects/01-cited-rag/scripts/export_portfolio_evidence.py`从已提交报告确定性导出。
- `evidence-manifest.json`记录输入报告、截图和页面制品SHA-256。

在P1项目目录执行：

```powershell
.\.venv\Scripts\python.exe scripts\export_portfolio_evidence.py
.\.venv\Scripts\python.exe scripts\export_portfolio_evidence.py --check
```

本地预览可使用Python标准库静态服务器；线上Pages仍只展示同一份确定性静态制品，不提供实时推理。
