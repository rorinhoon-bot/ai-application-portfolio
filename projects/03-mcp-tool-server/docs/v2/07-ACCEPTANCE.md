# P3 V2 离线验收

日期2026-09-16；**通过本机离线工程验收，可进入阶段C**。不等于新机器安装、跨平台、真实多用户或公开部署验收。

Git：`codex/p3-mcp-v2` / `dcb164e95059b060ffd6aebbaa093a7626177614`；无stage/commit/push。A已在根 `docs/integration/P1-READONLY-ACCEPTANCE.md` 完成。非P3既有文件逐个SHA-256核对，变化0；原工作树保留。

| 维度 | 本次证据 |
|---|---|
| 完整旧新回归 | P3 `.venv/Scripts/python.exe -m unittest discover -s tests -q`：**263 tests，254通过，9跳过，31.942s**；`evals/results/p3-v2-full-tests.txt` |
| 固定V2行为评估 | `PYTHONPATH=src`；`-m mcp_notes.v2.evaluate --output evals/results/p3-v2-baseline.json`：**16/16**，真实stdio协议，38份审计收据，读取重放一致 |
| 旧评估/演示 | `evals/run_d6_eval.py`：40/40（含C 11/11）；`demo/mcp_stdio_demo.py`：8/8；旧gold及结果未改 |
| 严格协议 | 实际list_tools输入/输出Schema、错误isError、structuredContent和兼容文本一致；实际Resource与快照hash |
| 工具安全 | 非法字段/类型/NFKC穿越/未知ID/默认写拒绝、登记后篡改/非法UTF-8/超限/缺失目录、审计前后故障及输出合同故障均运行验证 |
| 有界恢复 | 读协程超时、SDK超时、2次读上限、确定性错误不重试、写超时不重发、并发收据、可信Host批准与单文件重放 |
| 依赖/工作树 | `pip check`无破损；依赖锁未改，无安装；`git diff --check -- projects/03-mcp-tool-server docs/integration`通过 |

测试使用独立临时目录与自建stdio进程。旧HTTP测试只访问其自建回环进程，无既有服务操作；无外网、收费调用、.env或真实数据库访问。V1 D6中含历史计数/源码形态检查，保留但不作为V2功能证明；V2新增测试全部执行行为和协议。

## 验收边界

只读默认指无业务写权限，审计收据仍写入可信预创建目录。可选create_task只登记意图；批准仍在Tool外，不构成模型授权。安全读复用Windows句柄层；9项真实链接/平台专项未运行，不能计入通过。审计非签名、非防管理员篡改，资料只保证与批准快照一致，不保证事实正确。

P2内容质量未通过，保留首批2有限批准/4拒绝、修复后2有限批准/1拒绝；417/500分、109/109调用容量不变。C只允许脚本模型/离线夹具，不使用此验收解锁真实调用。设计与实现由助手完成，学习者独立讲解尚未验证。

下一步：先记录分支创建前基线，再 `git switch -c codex/graduation-integration`，创建后重核分支/HEAD/status/stat；保留工作树。随后写整合设计再实现业务。
