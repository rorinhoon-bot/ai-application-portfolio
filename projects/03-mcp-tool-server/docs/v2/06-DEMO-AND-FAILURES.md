# P3 V2 演示、失败案例与复盘

P3目录，现有 `.venv`，不安装依赖、不读.env：

```powershell
$env:PYTHONPATH='src'
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m mcp_notes.v2.evaluate
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

演示自动创建并清理独立临时审计目录，以真实SDK启动自己的stdio子进程，列出2个只读工具，执行16个固定案例，再验证search/read/replay。实际结果见 `evals/results/p3-v2-baseline.json`：16/16、38份开始/结束收据、重放正文一致、0模型调用。它是工具行为演示，绝不表示真实模型内容质量。

可手动启动只读服务；两个目录必须预先存在，审计目录须由当前OS用户独占，笔记只使用批准夹具：

```powershell
.\.venv\Scripts\python.exe -m mcp_notes.v2.server --notes-root <绝对白名单目录> --audit-root <绝对独占审计目录>
```

MCP Client通过stdio连接。不得在项目既有数据库/运行目录上尝试。只有另外指定 `--enable-write-intents` 才读取V1环境配置与可信身份文件并开放create_task；它仍只登记意图。批准用 `TrustedHostController`，不通过MCP。自动演示不启用写。

## 故障证据

- V1索引构建失败曾变成空成功。V2启动返回 `p3-startup-failed`，领域层 `index-build-failed`；不存在根的行为测试覆盖。
- 登记与读取之间文件被更改：`snapshot-invalid`，不输出部分快照；严格UTF-8与8KiB限制独立测试。
- 模型传入NFKC路径、未知身份字段：`invalid-arguments`；默认create_task为 `permission-denied`；approve为 `unknown-tool`。审计不保存原始攻击字符串。
- 审计开始失败：不执行工具；结束失败：返回 `audit-unavailable`，只有开始记录表示结果未知，不能推断回滚。
- 读协程挂起：`tool-timeout`；Client仅只读最多2次；写超时不重试。硬进程卡死须由Host外层超时终止；不能声称async超时能中断同步系统调用。
- 开发中首次strict socket审计阻断了Windows asyncio内部socketpair，stdio启动失败。改为已验证的外网阻断，允许事件循环内部回环；不提供HTTP监听工具。首次测试另一失败来自Windows换行自动转换，夹具改写原始UTF-8字节，正文哈希不做偷偷归一化。

## 限制与复盘

单机单可信OS用户；审计有哈希和no-replace，不防管理员改写，不是签名账本。快照启动后冻结，更新需新服务/新研究审批。启动枚举依赖可信小目录和外层进程期限；不提供任意目录扫描。9项历史链接/平台专项skip保留，Linux/WSL与真实多用户未验证。Python依赖沿用现有锁；未做新机器安装。

P3测试证明协议、安全和行为，不证明报告内容。P2真实内容验收未通过，预算417/500分、调用容量109/109；整合不得调用真实模型绕过。此次设计、编码、审查与执行均由助手完成；学习者独立解释尚未验证。
