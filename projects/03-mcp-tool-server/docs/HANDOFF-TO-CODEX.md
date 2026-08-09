# 接力文档：本地 MCP 工具服务（P3）后续开发交 Codex 接管

> 生成日期：2026-08-09
> 生成者：WorkBuddy（小迪）— D-4 设计包 design-only 阶段
> 目的：把 **`projects/03-mcp-tool-server`（P3 本地 MCP Notes 工具服务）** 的后续全部开发工作（D-4 实现 → D-5 → D-6 → 收尾）**交 Codex 接力**。本文件是接力上下文 + 纪律契约；详细设计见 `docs/D-4-design.md`。
> 仓库：`H:\暑假学习\编程学习\ai-application-portfolio`
> 项目目录：`projects\03-mcp-tool-server`
> 分支：`codex/p3-local-mcp-tool-service`
> 基线 HEAD：`b9fdff8`（D-3 实现提交；后续实现提交应在此 lineage 上**本地递进**，详见「提交与推送纪律」）

---

## 1. 项目当前状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| C（基础） | 已完成（历史基线） | unittest 149 → 164 → 现 226（217 执行 + 9 skip）；23 集成；6 入口；eval 11/11；demo 8/8 |
| D-1 | 本地提交（`94dd90d` 等），未 push/未 PR | 64-hex correlation_id + required subject + 入口泄露修复 |
| D-2 | 本地提交（`ba17a2d`→`905886a`→`09038cd`），未 push/未 PR | 跨平台原子(no-replace)发布一致性；`safe_task_write*.py` **零修改** |
| D-3 | 本地提交（`d14341d` 等），未 push/未 PR | `RuntimeIdentity` 单 subject 身份模型（v3 设计） |
| **D-4** | **设计完成（v1，第三轮修正），未实现** | 并发确认消费 + 多用户隔离；见 `docs/D-4-design.md`（本轮引入持久化 `PUBLISHING` 中间态修复崩溃恢复 P0） |
| D-5 / D-6 | 规划中 | 见 `DECISIONS.md` D-019…D-027、PRD §11 |

> **HEAD 冻结说明**：`b9fdff8` 冻结仅适用于「D-4 design-only 修订」阶段（设计不移动分支）。进入实现后，Codex 应在此 lineage 上做**本地提交**推进 HEAD；是否 push / 开 PR 见第 6 节纪律。

---

## 2. D-4 最终设计要点（Codex 实现依据）

完整设计：`docs/D-4-design.md`（§0–§10）。核心结论（已按 Codex 三轮复核意见修正）：

1. **跨进程唯一消费 = 四层纵深**（均非 WAL/连接池/Python 锁）：
   ① `BEGIN IMMEDIATE` 抢占 SQLite 文件写预约（RESERVED 锁），串行化所有终态动作；
   ② D-2 `publish_task_file` no-replace 原子无覆盖（物理文件至多一次）；
   ③ 条件 `UPDATE ... WHERE status=? AND subject=? AND correlation_id=?` + `cur.rowcount` 判定唯一消费者；
   ④ **持久化 `PUBLISHING` 中间态**（本轮新增，闭环崩溃恢复竞态）。
2. **`PUBLISHING` 状态机（本轮 P0 修复核心）**：
   - `PENDING → PUBLISHING`（approve 阶段 1 事务提交，**在发布文件之前**）→ `APPROVED`（阶段 2 提交，文件发布成功后）。
   - `reject`/`cancel`/`expiry` 仅在权威重读为 `PENDING` 时写负向终态；读到 `PUBLISHING` **不得写负向终态**，必须走 `_recover_publishing`（完成 `APPROVED` / D-2 证明无残留则回退 `PENDING` / 残留不可判定则失败关闭）。
   - 由此消除「文件已存在 + 负向终态」路径。
3. **`COMMIT` 异常 → 持久化状态未知**（非「必回 PENDING」）：尽力 `rollback` → 关连接 → **新连接重读权威状态（含 `PUBLISHING`）**；`APPROVED`→不发布；`PUBLISHING`→`_recover_publishing`；`PENDING`→安全重放；读失败→`task-write-failed` 失败关闭。区分 commit 阶段 `SQLITE_BUSY` 与一般 I/O 异常。
4. **乐观读无副作用**：身份/过期/终态的乐观预读不写库；任何 `EXPIRED`/audit/commit 均在 `BEGIN IMMEDIATE` 事务内且带守卫。
5. **审计写入时机（P1-a）**：成功路径在主事务 `COMMIT` **之后**以**独立 best-effort 事务**写入，失败不影响主结果；回滚路径不写终态审计。绝不把审计当作会被 `ROLLBACK` 丢弃的同事务事实。
6. **多用户隔离**：本地单 subject 下 `confirmations`/`task_id` 受 subject 绑定；audit 表无 subject 列（仅「单 subject 审计」）；真实多用户 blocked。
7. **错误语义**：复用既有稳定码；`database-busy`/`confirmation-in-progress` 为可选加法码（**T4 固定断言以复用 `task-write-failed` 为准**）；审计/失败均不泄露路径/用户名/正文/密钥/Cookie/鉴权头/原始异常。
8. **确定性测试（P1-c seam）**：引入私有连接工厂 `_make_connection(db_path)` + 包装 `_commit(conn)`/`_close(conn)`（module 级）作为测试 seam；**不直接 monkeypatch `sqlite3.Connection`**（C 实现不可实例替换）。测试用 `multiprocessing.Barrier`/`Event`/`Queue` 对齐竞态，**严禁 sleep 赌时序**，整体超时防死锁。覆盖 **T1–T9**（新增 **T9 = `PUBLISHING` 防负向终态**）。

---

## 3. 硬约束（实现阶段必须遵守）

- **不改 `safe_task_write*.py`**（D-2 零修改硬约束）。
- **不修改 P2、不修改 `projects/02-agent-research-workflow/`、不修改 `.workbuddy/`**（这些目录的现有修改与本接力无关，保持原样）。
- **不新增依赖**；优先标准库 `sqlite3`。
- **不把 `WAL` / 连接池 / Python 锁** 描述为跨进程并发安全方案（§1.2 明确否定）。
- **不把设计写成已实现**；不声称分布式事务、跨机原子性、真实多用户、真实链接验证或公开部署已完成。
- **不创建或运行真实 symlink/junction**；真实链接专项（D2-L1…L4）仍 skip / blocked。
- **不接模型、不联网、不公开部署**。
- **不泄露敏感信息**：审计/日志只存稳定事件类型 + 稳定错误码 + `task_id`/`confirmation_id`。

---

## 4. blocked-until-approved（实现阶段仍需用户单独批准，不得擅自做）

1. 真实多用户环境（多 OS 账户 / 多 subject / `per-subject task_root` / `audit` 增 `subject` 列）。
2. 真实 symlink/junction 夹具（D2-L1…L4）。
3. OS 原生凭证绑定（Windows SID / POSIX uid）。
4. 跨进程身份一致性断言机制（IPC / 共享凭据 / 启动握手）。
5. WSL/Linux/远程 runner 真实 POSIX 验证。
6. 公开部署 / 网络传输 / 公网并发负载。
7. 新增 `database-busy` / `confirmation-in-progress` 等错误码的最终采纳（可先复用 `task-write-failed`）。

---

## 5. 统一验证闸门（每片实现后必须复跑，不得降低）

- **226 项（217 执行 + 9 skip）** 单元测试零删除；**23** 集成、**6** 入口、eval **11/11**、demo **8/8**。
- `git diff --check`（仅历史 CRLF 提示非错误）、`pip check`、`compileall` 全绿。
- 新增 `tests/test_d4_concurrency.py` 为增量，确定性、无真实链接。
- 任何切片不得降低既有基线计数。

---

## 6. 提交与推送纪律（重要）

- **本地提交**：每个阶段（D-4 / D-5 / D-6）实现并验证通过后，做**本地提交**（推荐扁平或既有 lineage，勿引入会触发沙箱回滚的嵌套 ref 写法问题——如遇嵌套分支 ref 静默失败，用 `git update-ref` 或扁平分支名规避）。
- **不 push、不开 PR**：用户决定 **P3 全部阶段完成后统一处理 push 与 PR**（沿用 D-3 阶段约定）。在 D-4 及后续各阶段完成、但未全部完成时，**保持未 push、未建 PR**。
- 若 Codex 认为必须 push 才能继续（如需要 CI），先停下并报告用户，不得擅自 push。
- `safe_task_write*.py` 跨整个 P3 保持零修改。

---

## 7. Codex 接力执行顺序（建议）

1. **最终设计复核**：重读 `docs/D-4-design.md`（第三轮）与 `DECISIONS.md` D-028，确认 `PUBLISHING` 状态机闭环全部 P0/P1；输出 PASS / PASS-with-notes / NEEDS-FIX。若 NEEDS-FIX，先修设计文档（仍 design-only、未实现），再 proceed。
2. **实现 D-4**：
   - 改 `src/mcp_notes/tasks.py`：`approve` 两阶段 + `PUBLISHING`；`reject`/`cancel`/`expiry`（`_terminalize`）同写预约 + 读 `PUBLISHING` 走 `_recover_publishing`；新增 `_recover_publishing`；审计独立 best-effort 事务；COMMIT 异常走 §1.5 恢复；引入 `_make_connection`/`_commit`/`_close` seam。
   - 新增 `tests/test_d4_concurrency.py`（T1–T9）。
   - 复跑统一基线（§5）。
   - 本地提交 D-4（未 push、未 PR）。
3. **D-5 / D-6**：按 `DECISIONS.md` / `PRD.md §11` 继续，遵守相同硬约束与验证闸门；每阶段本地提交、不 push/PR。
4. **收尾**：全部阶段完成后，向用户报告，由用户决定是否 push / 开 PR。

---

## 8. 关键文件索引

- 设计：`docs/D-4-design.md`（D-4 详细设计，v1 第三轮）、`docs/D-3-design.md`、`docs/D-2-design.md`
- 决策：`DECISIONS.md`（D-019…D-028）
- 规划：`docs/PRD.md`（§10/§11.2）、`docs/ARCHITECTURE.md`（§7）、`STATUS.md`
- 实现目标：`src/mcp_notes/tasks.py`（`approve`/`reject`/`cancel`/`expiry`）、`src/mcp_notes/safe_task_write.py`（**不改**）、`src/mcp_notes/identity.py`、`host.py`、`server.py`
- 测试：`tests/test_d4_concurrency.py`（新增）、既有 `tests/`
