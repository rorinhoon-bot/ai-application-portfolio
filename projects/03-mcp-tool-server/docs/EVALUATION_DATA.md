# P3 固定离线评估方案

- 版本：v0.3（Slice A / B1 / B2a 离线核心已落地；C 阶段已完成 MCP 真实本地 stdio 集成与固定离线评估）
- 日期：2026-08-01（B2a 更新 2026-08-02）
- 当前状态：D-6 已冻结并真实运行完整 40 例：`evals/cases/p3-service-v1.json`、`evals/gold/p3-service-v1-gold.json`、`evals/run_d6_eval.py` 与 `evals/results/p3-service-v1-baseline.json`。结果为 40/40；其中前 11 例原样复跑 C 阶段金标准，新增 29 例覆盖受控写、身份、PUBLISHING 恢复、参数拒绝和最小审计。所有资料原创、虚构、离线、确定性；不读私人笔记、不调模型、不访问外网。

## 1. 数据边界与快照

后续评估资料全部原创、虚构、UTF-8、离线且确定性：例如三份普通项目笔记、一份含提示注入文本笔记、一份含 URL/命令/伪造路径笔记。不得下载真实笔记，不得读取用户真实私人笔记，不得用模型生成评估答案。

实现前冻结：

- `evals/fixtures/notes-v1/`：只含允许的原创 `.md` 笔记。
- `evals/fixtures/security-v1/`：临时生成的符号链接、junction/reparse point、未登记文件、过大内容和冲突目标；不提交真实外部路径。
- `evals/cases/mcp-service-v1.json`：固定输入、可信测试主体、可信调用关联 ID、人工动作脚本和期望分类。
- `evals/gold/mcp-service-v1-gold.json`：检索金标准、期望终态、写入计数、任务 ID 关系和禁止泄露事实。
- `evals/gold/tasks-core-v1.json`：**（Slice B2a 已落地）** 受控写核心固定金标准，12 个场景：未确认、批准、拒绝、取消、过期、身份错绑、内容变化（同关联 ID 不同内容 → 幂等冲突）、重复请求（安全重放）、重复批准（已消费幂等）、已批准超期再批准（P0-2：`unchanged` + `confirmation-already-consumed`，已批准记录不被过期改写）、冲突文件（no-replace，既存文件不覆盖）、原子写入失败（注入 `write_failure` 故障，即 `NtCreateFile` **成功创建后** `WriteFile` 返回失败 → `task-write-failed`、确认 `PENDING`、清理成功路径无残留）。全部原创虚构、无密钥/无绝对路径。金标准场景数保持 **12**（本轮未新增场景）；`NtDeleteFile` 非成功（清理失败）情形**不冒充金标准成功**，仅以代码级回归覆盖（见下）。
- **创建成功后写入失败回归（3 项，`tests/test_create_task.py::TestWriteFailureAfterCreate`，均为清理成功路径）**：在 `NtCreateFile` **成功创建最终文件之后**分别注入 `WriteFile` 失败、`FlushFileBuffers` 失败，以及 `approve` 完整路径上的写入失败。判定：不外泄原始异常、返回稳定 `task-write-failed`、任务目录内 `.json` 计数为 `0` 且无 `.tmp` / `~` / `.partial` 临时残留、确认记录仍为 `PENDING`、移除故障后重放返回 `created`。故障注入只作用于原生写/刷新调用，不修改金标准数据。
- **清理/回查收口回归（4 项，`tests/test_create_task.py::TestConflictReadonlyAndDeleteFailure`）**：(1)(2)(3) 冲突只读转换失败——冲突文件存在 + 原生冒烟完成 + 分别注入 `msvcrt.open_osfhandle` / `os.fdopen` / 真实文件 `read` 抛 `OSError`；`approve` 返回稳定 `task-write-failed`、confirmation 仍 `PENDING`、无原始异常文本，且**退出 mock 后冲突文件可被立即 `os.remove`**（证明 `_read_existing_json` 已精确释放仍归本函数所有的 HANDLE/fd，无遗留锁）；(4) 删除失败——`NtCreateFile` 成功后 `WriteFile` 失败触发清理路径，且 `NtDeleteFile` 返回非成功 NTSTATUS（`0xC0000043`）不抛异常，清理失败**不得静默吞掉**，返回脱敏稳定 `task-write-failed`、不回显 NTSTATUS/路径，确认保持 `PENDING`，且**不错误断言目录必空**（残余可能仍在）。
- `evals/results/mcp-service-v1-baseline.json`：首次真实执行生成；禁止用期望值伪造实际结果。

冻结后为目录清单、逐文件 SHA-256、总字节数、案例数和金标准版本生成 `source_snapshot_id`。任何资料修正必须创建 `v2`，不得覆盖 `v1`、P2 `workflow-v1`、P2 金标准、评估资料或演示制品。

## 2. 计划案例集

首版固定 **40 个案例**。数量与分类在实现前锁定；每例都有唯一 ID、输入、前置文件状态、可信身份/关联 ID、人工动作、预期稳定结果、预期文件数和禁止泄露字段。

| 分类 | 案例数 | 最少覆盖 |
|---|---:|---|
| 1. 正常关键词检索 | 4 | 标题、正文、大小写、多个命中与 5 条上限 |
| 2. 空/过长/未知字段/非法类型 | 5 | 空白、81 字符、未知键、数组、对象与 URL/命令语义 |
| 3. 无结果与无权限结果 | 3 | 无匹配、未登记笔记、已删除登记项；不泄露路径/存在性 |
| 4. 路径穿越与链接 | 6 | `..`、绝对路径、符号链接、junction、未知 reparse point、未登记文件 |
| 5. 笔记提示注入与危险文本 | 3 | “忽略规则”、命令、URL、伪造绝对路径；结果仅为不可信截断文本 |
| 6. 确认缺失/批准/拒绝/取消 | 4 | 四个状态，每例核验写入数 |
| 7. 旧确认/身份错绑/重复批准/重复写入 | 4 | 到期、主体不匹配、确认已消费、关联 ID 重放 |
| 8. 幂等/冲突/原子失败 | 4 | 同调用重放、关联 ID 内容冲突、既有目标、临时写或发布失败 |
| 9. MCP Host/Client 集成 | 4 | Resource、成功搜索、待确认写、非法参数或确认拒绝 |
| 10. 网络阻断与敏感扫描 | 3 | socket/HTTP 尝试拦截、日志/结果扫描、Git 样例扫描 |
| **总计** | **40** | 成功、失败、安全与协议路径 |

第 9 类已由 C 阶段以真实本地 stdio Host/Client 执行并验证（`tests/test_mcp_integration.py` + `demo/mcp_stdio_demo.py` + `evals/run_c_phase_eval.py`）。

> **B2a 已落地（2026-08-06）**：计划分类 6（确认缺失/批准/拒绝/取消）、7（旧确认/身份错绑/重复批准/重复写入）、8（幂等/冲突/原子失败）的受控写核心已由固定金标准 `evals/gold/tasks-core-v1.json`（12 场景）+ `tests/test_create_task.py`（53 项，含 3 项“创建成功后写入失败”故障注入回归、3 项冲突只读转换失败回归与 1 项删除失败回归）离线覆盖，并配套网络阻断与敏感扫描。上述 40 例仍是完整目标，未因 B2a 提前宣称完成；**其中第 9 类（MCP Host/Client 集成）已由 C 阶段真实实现并验证，第 6/7/8 类的成功/失败/身份/过期路径在 C 阶段经 `TrustedHostController` + stdio 集成测试再次覆盖**。

> **C 阶段固定离线评估（已落地，2026-08-02）**：新增 `evals/gold/c-phase-v1.json`（11 场景固定期望）与 `evals/run_c_phase_eval.py`（v2 进程内 `Client(build_server(config))` 对比金标准），全部通过；并新增 `tests/test_mcp_integration.py`（**20 项**真实 stdio 子进程集成测试，父进程与 Server 子进程均默认阻断外部网络，全部通过）、`tests/test_server_entry.py`（**2 项**入口 / 配置测试：生产入口不创建任务根、默认笔记根指向仓库夹具）与 `demo/mcp_stdio_demo.py`（真实 stdio 子进程 8 项成功 + 失败演示全部通过）。11 例覆盖：tools 列表不含确认动作、search 成功（命中 2）/ 非法关键词、create 返回 PENDING（`^task-[0-9a-f]{16}$` / `^conf-[0-9a-f]{16}$`）/ 非法标题、Host approve→发布文件、reject/cancel 终态、未知确认 `confirmation-required`、跨部署主体的 Host 批准 `confirmation-identity-mismatch`（D-018 后由“另一部署主体的 Host”驱动，不再伪造上下文）。20 项集成测试另覆盖：4 项 Tool 参数脱敏（非字符串 / 未知字段 / 缺必填 → 稳定 `invalid-arguments`，响应不含 Pydantic 文本 / URL / 堆栈）、2 项重放幂等（同内容 → 同 `task_id`/`confirmation_id`；不同内容 → 相互独立）、跨主体 Host approve/reject/cancel 全拒绝、2 项子进程网络阻断（外部地址被拒、回环不被该机制拦截）。评估只用原创虚构夹具，不读私人笔记、不调模型；运行时只用本地 stdio 管道、不发起对外网络连接；不泄露路径/正文/原始异常。（注：20 项 / 2 项为 C 阶段历史基线；当前统一基线 196 项 / 23 集成 / 6 入口，见 STATUS）

## 3. 金标准与判定

### 检索金标准

每个正常检索例固定允许 `note_id` 顺序、标题、匹配计数、摘录最大长度与禁止字段。评估器独立从冻结输入和金标准比较实际 Server/核心结果；不得从 `expected` 反写实际输出。

### 写入金标准

每例固定：请求终态、确认终态、应否产生任务文件、任务文件数量、`task_id`/关联 ID 关系、是否必须返回 `UNCHANGED`、是否必须保留旧文件字节，以及是否禁止回显内容。批准成功例的任务正文也用冻结规范 JSON 比较；其余例期望文件数为 `0`。

### 安全金标准

所有安全拒绝例必须同时满足：稳定允许错误码、网络尝试 `0`、禁止字段泄露 `0`、任务写入 `0`（幂等成功重放除外，且文件数仍为 1）、根目录外访问尝试 `0`。无权限路径不返回真实绝对路径、文件名或链接目标。

## 4. 指标与门槛

| 指标 | 分母 | 目标 |
|---|---|---:|
| 案例通过率 | 40 全部案例 | `100%` |
| 正常检索正确率 | 4 正常检索案例 | `100%` |
| 参数拒绝正确率 | 5 非法参数案例 | `100%` |
| 路径/链接安全拒绝率 | 6 路径案例 | `100%` |
| 提示注入不扩大权限率 | 3 危险文本案例 | `100%` |
| 未授权写入数 | 预计不写入的案例 | `0` |
| 幂等正确率 | 4 幂等/冲突/原子案例 | `100%` |
| Host/Client 集成通过率 | 4 集成案例 | `100%` |
| 网络尝试数 | 全部测试 | `0` |
| 敏感数据泄露命中 | 结果、日志、夹具、Git 扫描 | `0` |

比例必须保存 `numerator`、`denominator` 和整数 basis points；不得只保存百分比。任一安全指标不达标即整体评估失败，即使功能成功率为 100%。

## 5. 测试隔离与扫描

- 普通测试默认安装网络阻断器；任何 DNS、socket、HTTP 或 SDK 网络尝试立即失败并记录最小分类，不写 URL/请求头。**Slice A 已实现 `tests/_network_block.py` 的 `NetworkBlockedTestCase` 基类与验证用例，现有单测默认继承该底座。**
- 所有文件测试在系统临时目录复制或生成夹具；不读取真实用户目录，任务目标仅为测试专用受控根。
- Windows-only junction/reparse point 案例在不支持的平台显式标为 `skipped-with-reason`，不能伪装通过；Windows P3 主环境必须实际执行。
- 扫描模式覆盖典型 API key、Bearer、Cookie、授权头、连接串、私钥标记、绝对用户路径与未脱敏 traceback；扫描结果只报告文件与类别，不回显疑似秘密。
- 测试不修改 P2 的 `workflow-v1`、金标准、来源快照、结果或演示制品。

## 6. 失败案例报告格式（计划）

基线每例记录 `case_id`、类别、实际终态、稳定错误码、实际任务文件数、实际网络次数、敏感扫描计数和 `passed`。不记录私人路径、笔记/任务正文、密钥、Cookie、鉴权头、完整 MCP 消息、完整异常或临时目录。失败分类使用 PRD 第 7 节。

## 7. 当前限制

当前方案不证明真实模型质量、私人笔记兼容性、生产多用户身份、并发负载、跨平台一致性、真实 Host 支持范围、模型 token/费用或公开部署。首次结果只能证明冻结原创夹具上的本地服务可靠性与安全边界。
