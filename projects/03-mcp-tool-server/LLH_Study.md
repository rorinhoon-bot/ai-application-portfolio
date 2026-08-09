# P3 学习复盘：本地 MCP 安全工具服务

1. MCP Tool 只接业务文本；身份和人工批准在 Tool 外。
2. 笔记正文是不可信数据，命令或路径不能升级权限。
3. 任务名由服务端 ID 派生，用 no-replace 发布，不能覆盖已有任务。
4. 并发批准靠 SQLite `BEGIN IMMEDIATE`、条件更新和 `PUBLISHING`；不靠 Python 锁或 WAL。
5. HTTP 默认关闭；启用时只能绑定本机回环。

自测：为什么 PUBLISHING 不能回退 PENDING？因为写层稳定错误码不能证明文件无残留。

```powershell
Set-Location projects\03-mcp-tool-server
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.venv\Scripts\python.exe evals\run_d6_eval.py
```
