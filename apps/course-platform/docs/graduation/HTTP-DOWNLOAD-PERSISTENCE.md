# 身份模式 HTTP 下载与本地文件复核

2026-09-22。工作树 `codex/course-platform-ui`，阶段开始 HEAD `be42ee59d2c28fb2ea0edaef4a3ca4efb73d4c0b`，状态干净。只扩展本应用现有离线端到端测试，不操作原 P1/P2/P3 数据库、容器、服务或真实模型账本；所有账户、资料、项目和 ZIP 文件都在测试临时目录。

`test_reviewer_finishes_real_offline_delivery` 先由研究者导入两份原创合成资料并冻结项目，另一名审核者批准范围、批准修订后的报告，再通过实际 loopback HTTP 下载。新增验证：审核者与项目所有者均收到 200、`application/zip` 和附件响应；两次包字节哈希一致；HTTP 响应字节写入本机临时 ZIP 后可原样读回；独立 `frozen_bundle_cli.py` 对该磁盘文件返回 `bundle_consistent: true`；访问审计分别记录两人的下载。原测试继续覆盖研究者不能自批、旧报告指纹失效及真实离线 P1/P2/P3 链路。

仓库根目录运行：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B -m unittest discover -s apps/course-platform/tests -p test_auth.py -k test_reviewer_finishes_real_offline_delivery -v
```

最终专项结果：**1/1 通过，41.360秒**，0失败/0错误；本次未重跑完整应用套件。上一阶段未改业务代码时完整回归为61/61、0跳过，见 [dependency-readiness-tests.json](../results/dependency-readiness-tests.json)。本轮只修改测试与文档，未增加依赖、下载或真实模型调用。

**证据边界：**上述操作由 Python HTTP 客户端保存 ZIP，证明服务响应和本机文件/独立复核链路，不等于浏览器按钮下载到操作系统下载目录。浏览器控制接口再次报 `Browsers: Error: nodeRepl.fetch request failed`，所以干净检出三角色 UI 与浏览器下载落盘仍未验收。后续工具恢复后用隔离新状态和新浏览器会话复演，核对实际下载路径、文件哈希和 CLI 复核；不得把本测试改写为浏览器验收。
