# D-4 详细设计：并发确认消费与多用户隔离（设计包 v1）

> 状态：**设计包 v1（design-only；未实现、未暂存、未提交、未 push、未建 PR）**。分支：`codex/p3-local-mcp-tool-service`；基线 HEAD：`b9fdff8`。
> 修订历史：三轮设计复核已收紧为 `PUBLISHING` 两阶段状态机；其中“发布失败可由 D-4 回退 `PENDING`”已被最终复核否决。**D-4 实现现已落地、待本地提交**：发布失败一律保留 `PUBLISHING` 失败关闭；D-2 对外稳定错误码不用于推断零残留。
> 范围：仅设计，不写业务代码、不安装依赖、不创建 `.venv`、不运行真实 symlink/junction、不 push、不建 PR、不进 D-5/D-6。
> 与 D-3 的衔接（D-3 实现已由本地提交 `d14341d` 落地）：D-4 在 D-3 的 `RuntimeIdentity` / **单 subject** 身份模型之上叠加**跨进程并发消费的唯一性**；**不改变 D-3 身份来源与信任边界**，也不引入多 subject。

**设计目标（对应 PRD §11.2 D-4 行 DoD）**：① 确认消费用**事务中的条件更新**（`PENDING`→终态一次，以 `UPDATE ... WHERE status='PENDING'` 的 rowcount 判定）；② 跨进程并发批准同一 confirmation **仅一个发布**，其余返回稳定已消费结果且**绝不写第二个文件**；③ 其余调用返回稳定已消费结果、绝不写第二个文件；④ **引入持久化 `PUBLISHING` 中间态，保证「文件已存在时不会被 `reject`/`cancel`/`expiry` 写成负向终态」**；⑤ 多用户之间确认记录/任务文件/审计事件**隔离（本轮隔离边界见 §3，真实多用户 blocked）**；⑥ **不得把“连接池 / WAL / Python 锁”描述为并发安全方案**。

---

## 0. 范围与门面确认

- D-4 收敛在「跨进程并发确认消费的唯一性」与「本地单 subject 模型下的隔离边界」；不进 D-5/D-6；不创建/运行真实 symlink/junction；不调用模型、不联网、不引入依赖。
- 现有相关代码点（已实现，D-4 设计须兼容、不得回退）：
  - `src/mcp_notes/tasks.py`：`approve` / `reject` / `cancel` 当前为 **check-then-act**（SELECT 读 `PENDING` → 发布 → **无 `WHERE status` 守卫**的 `UPDATE`），无跨进程唯一消费保证；且**过期（`EXPIRED`）写动作发生在无守卫的事务外**（见 §1.1 / P1-5）。
  - `src/mcp_notes/safe_task_write.py`：`publish_task_file(task_root, task_id, payload)` 经 D-2 no-replace（`O_CREAT|O_EXCL` / `NtCreateFile(FILE_CREATE, OBJ_DONT_REPARSE)`）原子无覆盖，返回 `"created"` / `"unchanged"`，抛 `SafeWriteError`（稳定码）。
  - `src/mcp_notes/host.py`：`TrustedHostController` 用自身 `RuntimeIdentity.subject` + 存储 `correlation_id` 重建 `TrustedContext`。
  - `src/mcp_notes/identity.py`：`RuntimeIdentity`（单 subject，`version:1` schema）。
- D-4 **明确不实现真实多用户**（多 subject / 多 OS 账户）；该能力标 **blocked-until-approved**（见 §8）。

---

## 1. 并发确认消费：写预约串行化 + 条件更新 + PUBLISHING 中间态（唯一消费闸门）

### 1.1 现状缺口

当前 `approve` 流程：

```
SELECT 行 →（身份/过期/终态检查）→ _publish_task_file(...) →
UPDATE confirmations SET status='APPROVED', consumed_at=? WHERE confirmation_id=?
```

问题：

1. `UPDATE` **无 `status='PENDING'` 守卫**，也**无 `subject`/`correlation_id` 在原子语句内重断言**。两个进程可同时读到 `PENDING`、各自调用 `publish_task_file`、各自执行无守卫 `UPDATE`——都把状态置 `APPROVED` 并各自返回 `created`/`unchanged`，**失去「唯一消费者」语义**（loser 不应再被视作成功发布）。
2. `reject` / `cancel`（`_terminalize`）同样用无守卫 `UPDATE`。若进程 A 已 `approve` 成功（发布文件、`APPROVED`），进程 B 并发 `reject` 的无守卫 `UPDATE` 可把状态**覆盖为 `REJECTED`**，破坏「文件已发布则状态终态」不变量（文件在、状态却 REJECTED）。
3. **（P0，Codex 复核指出）原始设计的「先发布、后条件 `UPDATE`」发生在 `BEGIN IMMEDIATE` 之外**，存在交错：A `approve` 乐观读 `PENDING` → B `reject` 乐观读 `PENDING` 且条件 `UPDATE` 成功写 `REJECTED` → A 发布文件成功 → A 条件 `UPDATE` `rowcount==0`。结果：**文件存在、DB 为 `REJECTED`**。
4. **（P0，本轮崩溃恢复漏洞）即便已用 `BEGIN IMMEDIATE` 把「发布 + 条件 UPDATE」包进同一事务**，仍存在崩溃恢复竞态：A `approve` 发布文件成功 → `COMMIT` 前崩溃（SQLite 自动回滚为 `PENDING`，文件已存在）→ 随后 B `reject`/`cancel`/`expiry` 取得写预约后读到 `PENDING`，可写成 `REJECTED`/`CANCELLED`/`EXPIRED`。结果**又是「文件存在、DB 负向终态」**。根因：状态机只有 `PENDING`/`APPROVED`，`PENDING` 被错误地等同于「任何重放都安全」——但 `PENDING` 并不蕴含「文件不存在」。
5. **（P1-5）过期动作无事务守卫**：当前 `approve`/`_terminalize` 在乐观读后、未取写预约前就可能把 `PENDING` 改写 `EXPIRED`（无 `WHERE status='PENDING'` 守卫、不在 `BEGIN IMMEDIATE` 事务内），并发下可被另一进程的 `APPROVED` 提交覆盖，或自身在写 `EXPIRED` 后被另一进程重复消费——终态转换非原子。

### 1.2 设计决定：写预约串行化 + 条件更新 + no-replace 发布 + PUBLISHING 中间态（四层纵深）

跨进程唯一消费来自**四点协同**，**均不是 WAL / 连接池 / Python 锁**：

1. **`BEGIN IMMEDIATE` 写预约（SQLite 文件级 RESERVED 锁，串行化终态动作）**：`approve` / `reject` / `cancel` / `expiry` 在**读权威状态之前**即 `BEGIN IMMEDIATE`，于事务起点抢占 SQLite 写预约（RESERVED 锁）。在该锁释放（commit/rollback）之前，其它进程无法取得写预约——终态动作被**完整串行化**。这是 SQLite 文件锁（合法跨进程机制），**不是** Python `threading.Lock`、连接池或 WAL。
2. **D-2 `publish_task_file` 的 no-replace 原子无覆盖**：无论多少进程发布同一 `task_id`，物理文件**至多被创建一次**；其余得 `"unchanged"`，**绝不二次写入**。文件系统层跨进程保证。
3. **sqlite3 条件 `UPDATE`**（`UPDATE ... WHERE confirmation_id=? AND status='PENDING' AND subject=? AND correlation_id=?` 或 `... AND status='PUBLISHING' ...`），以 `cur.rowcount` 判定唯一消费者：影响 **1 行**=胜者；影响 **0 行**=已被消费（或身份不匹配）→ 返回稳定「已消费」结果，**不得写 `APPROVED`、不得再发布**。`rowcount` 作为**纵深保护**。
4. **持久化 `PUBLISHING` 中间态（本轮新增，闭环崩溃恢复 P0）**：`approve` 在**发布文件之前**先以一次**独立、已提交的**事务把 `PENDING` 改写为 `PUBLISHING`（阶段 1 提交），之后才发布文件、再以第二次事务把 `PUBLISHING` 改写为 `APPROVED`（阶段 2 提交）。`PUBLISHING` 是「发布进行中、终态 `APPROVED` 尚未落盘」的持久信号。**任何 `reject`/`cancel`/`expiry` 读到 `PUBLISHING` 都不得写负向终态**——它们必须进入 `PUBLISHING` 恢复并完成既有发布；恢复失败则保持 `PUBLISHING`、失败关闭，从而消除「文件已存在 + 负向终态」路径。

> **明确否定（硬约束）**：`WAL` 只是日志模式；**连接池**是单进程内连接复用；**Python `threading.Lock`** 仅限同进程内线程——三者**都不能提供跨进程唯一消费**，且**都不是本设计的并发方案**。本设计的正确性**只**来自：① `BEGIN IMMEDIATE` 抢占的 SQLite 文件写锁（终态动作串行化）+ ② no-replace 文件发布 + ③ 条件 `UPDATE` + `rowcount` 纵深 + ④ 持久化 `PUBLISHING` 中间态。**`busy_timeout` 只是缓解 `SQLITE_BUSY` 的等待窗口，绝不当作正确性保证**——正确性由写预约串行化 + 条件 `UPDATE` + `PUBLISHING` 状态机保证，而非靠超时等待碰运气。

### 1.3 推荐算法（两阶段 + PUBLISHING + BEGIN IMMEDIATE 内权威重读 → COMMIT 异常恢复）

状态机（`status TEXT`，无 CHECK，无需改表结构）：
`PENDING → PUBLISHING`（approve 阶段 1 提交）→ `APPROVED`（approve 阶段 2 提交，文件发布成功后）；
`PENDING → REJECTED` / `CANCELLED` / `EXPIRED`（reject/cancel/expiry，仅当权威重读为 `PENDING`）；
**`PUBLISHING` 永不被任何动作改写为负向终态**——读到 `PUBLISHING` 走 §1.3 末尾的恢复例程。

```python
def approve(self, confirmation_id, trusted_context):
    # 1) 形状/格式校验（_check_context / confirmation_id 格式）→ 失败稳定码，不取锁、不发布
    # 2) 乐观 SELECT 快路径（不取写锁、不写库、不产生任何副作用）：
    #    - 身份不匹配(subject/correlation_id) → confirmation-identity-mismatch
    #    - 已终态(APPROVED/REJECTED/CANCELLED/EXPIRED) → already_consumed / mismatch
    #    - PUBLISHING → 进入 PUBLISHING 恢复例程（见步骤 7），不发起新 approve
    #    - PENDING → 落入下一步取锁；此步【绝不】写 EXPIRED / 写 audit / commit
    # 3) BEGIN IMMEDIATE（抢占写预约）
    # 4) 事务内权威重读 status：
    #    - 终态 → ROLLBACK；返回 already_consumed / mismatch
    #    - PUBLISHING → ROLLBACK；进入 PUBLISHING 恢复例程
    #    - PENDING → 阶段 1：UPDATE confirmations SET status='PUBLISHING'
    #                 WHERE id=? AND status='PENDING' AND subject=? AND correlation_id=?
    #        rowcount==1 → COMMIT 阶段 1（PUBLISHING 现已持久）
    #        rowcount==0 → ROLLBACK；返回 already_consumed / mismatch（输掉写预约竞争）
    # 5) BEGIN IMMEDIATE（阶段 2 新事务：发布文件 + 写 APPROVED）
    #    权威重读（仍应为 PUBLISHING；若异常变化按对应分支处理）
    #    _publish_task_file(task_id, payload)：
    #      - 成功(created/unchanged) →
    #          UPDATE confirmations SET status='APPROVED', consumed_at=?
    #          WHERE id=? AND status='PUBLISHING' AND subject=? AND correlation_id=?
    #          rowcount==1 → 更新 idempotency → COMMIT 阶段 2 → APPROVED；
    #                       审计(approve_ok) 以【独立 best-effort 事务】写入（见 §4.2）；
    #                       返回 outcome（created / unchanged，见 T1 定义）
    #          rowcount==0 → ROLLBACK；进入 PUBLISHING 恢复例程（他人已解决）
    #      - TaskPublishError（safe_task_write 失败）：
    #          D-2 对外只给稳定错误码，不能向 D-4 证明“文件绝无残留”；
    #          一律保留已提交的 PUBLISHING，不回退 PENDING，ROLLBACK 当前事务，
    #          返回 task-write-failed 失败关闭。后续仅能重新走 _recover_publishing。
    # 6) 任一 COMMIT 抛异常 → 进入 §1.5 恢复合同（持久化状态未知；新连接重读须处理 PUBLISHING）

def _terminalize(self, confirmation_id, trusted_context, negative_status):
    # reject / cancel / expiry 统一入口
    # 1) 乐观 SELECT 快路径（同步骤 2，无副作用）
    # 2) BEGIN IMMEDIATE
    # 3) 权威重读：
    #    - 终态 → ROLLBACK；already_consumed / mismatch
    #    - PUBLISHING → ROLLBACK；进入 PUBLISHING 恢复例程（完成发布→APPROVED→already_consumed；
    #                  或恢复仍失败→task-write-failed 失败关闭）。恢复不得回退 PENDING，
    #                  更不得在已释放事务后复用旧快照写 negative_status。
    #                  【绝不】在此直接把 PUBLISHING 改写为 REJECTED/CANCELLED/EXPIRED
    #    - PENDING → UPDATE status=<negative> WHERE id=? AND status='PENDING' AND subject=? AND correlation_id=?
    #          rowcount==1 → idempotency/审计(独立 best-effort) → COMMIT → 返回对应稳定码
    #          rowcount==0 → ROLLBACK；already_consumed / mismatch

def _recover_publishing(self, confirmation):
    # 读到 PUBLISHING 时的恢复例程（approve 乐观读、_terminalize、以及 §1.5 COMMIT 异常新连接重读共用）
    #    _publish_task_file(task_id, payload)：
    #      - 成功(created/unchanged) → UPDATE status='APPROVED'
    #          WHERE id=? AND status='PUBLISHING' AND subject=? AND correlation_id=?
    #          rowcount==1 → COMMIT → 返回 (APPROVED, already_consumed)  # 原 approve 胜出
    #          rowcount==0 → ROLLBACK → 重读：APPROVED→already_consumed；其它终态→对应码
    #      - 任意 TaskPublishError → 保留 PUBLISHING → ROLLBACK → task-write-failed 失败关闭。
    #        D-2 的相同稳定码既可能来自已清理也可能来自残留未知，D-4 不得猜测并回退 PENDING。
```

- **`reject` / `cancel` / `expiry` 同步改造且同样 `BEGIN IMMEDIATE`**：均在写预约内权威重读；仅当 `status='PENDING'` 才写负向终态；读到 `PUBLISHING` 走恢复例程，**绝不把 `PUBLISHING` 覆盖为 `REJECTED`/`CANCELLED`/`EXPIRED`**，且**永不调用发布层去发起一次「新 approve」**（恢复例程的发布是 no-replace 完成既有发布）。因二者都先取写预约，`reject`/`cancel`/`expiry` 不可能在 `approve` 已提交 `PUBLISHING` 后、阶段 2 前插入负向终态。
- 身份在乐观 SELECT（步骤 2）与条件 `UPDATE`（步骤 4/5）**双重断言** `subject=? AND correlation_id=?`；写预约又叠加了事务级串行化，**纵深防御**。
- **乐观读不产生副作用（P1-5）**：步骤 2 只允许「无写」的判定（身份不匹配 / 已终态 / PUBLISHING 短路）；**任何 `EXPIRED` 持久化写、任何 `audit` 写、任何 `commit` 都必须发生在步骤 3–5 的 `BEGIN IMMEDIATE` 事务内**，且 `EXPIRED` 的转换必须带 `WHERE status='PENDING' AND subject=? AND correlation_id=?` 守卫。
- **T1「created」定义（修正，P1-b）**：**逻辑审批提交胜者**（阶段 2 提交 `APPROVED` 成功）即返回 `created`——即便崩溃恢复时物理文件为 `unchanged`（文件可能由**上一轮已崩溃的旧进程**写出），只要本次是首次成功提交 `APPROVED`，仍返回 `created`。只有「之后对已成 `APPROVED` 的重放（含 §1.5 恢复后新连接读到 `APPROVED`）」才返回 `unchanged` + `confirmation-already-consumed`。**不得表述为「文件创建者与 SQL 胜者为同一进程」**——崩溃恢复时物理文件可来自旧进程，二者不必同进程；统一概念是「逻辑审批提交胜者」。阶段 1 不写 `consumed_at`；该字段仅由最终 `APPROVED` 或负向终态转换写入。

### 1.4 事务边界、BEGIN IMMEDIATE 与 SQLite 锁

- **`BEGIN IMMEDIATE` 是正确性核心，不是可选项**：它在事务起点即抢占 SQLite **RESERVED 写锁**，使 `approve`/`reject`/`cancel`/`expiry` 完整串行化（见 §1.2 第 1 点）。多进程写被 SQLite 文件锁串行化，`rowcount` 在持有写预约的上下文里具权威性。
- 连接初始化设 `PRAGMA busy_timeout`（如 `5000` ms）仅作**缓解**：当写预约被他者持有时，本连接**等待**而非立即 `SQLITE_BUSY` 失败。它是**工程舒适度**，不是正确性保证——即便 `busy_timeout=0`，写预约 + 条件 `UPDATE` + `PUBLISHING` 状态机仍能保证正确（只是更易撞 `SQLITE_BUSY`）。**不得把 `busy_timeout` 描述为并发安全机制**。
- **显式事务包裹**：两阶段 `approve`（`BEGIN IMMEDIATE` → 重读 → 阶段 1 写 `PUBLISHING` → `COMMIT`）与（`BEGIN IMMEDIATE` → 重读 → 发布 → 阶段 2 写 `APPROVED`/`PENDING` → idempotency/audit → `COMMIT`）各自在同一连接、同一事务内；多语句不拆分到隐式事务。
- **`BEGIN IMMEDIATE` 超时（取锁失败）**：若 `BEGIN IMMEDIATE` 在 `busy_timeout` 内仍拿不到 RESERVED 锁 → `SQLITE_BUSY` → 此时**事务尚未开始、无任何写已发生** → `ROLLBACK`（实为无操作）→ 返回稳定码（见 §4）→ 调用方可重放。这**与 COMMIT 失败不同**：取锁失败可确定「未写入」，故称「保持 `PENDING`」成立；COMMIT 失败**不可**作此断言（见 §1.5）。
- **`COMMIT` 失败语义（P0-1）**：见 **§1.5 恢复合同**——**持久化状态视为未知**，不得宣称「DB 回 `PENDING`」；`rollback` 仅释放本连接存活事务、不构成「已证明 PENDING」；须关闭本连接、用新连接重读权威状态（**含 `PUBLISHING`**）。**这是本地单库恢复，非分布式事务**。
- `sqlite3.Error`（非 COMMIT 路径） → `ROLLBACK` → 由调用方映射稳定码（**不得泄露原始异常**）。
- 连接为**每进程 / 每 handler 独立** `sqlite3.connect(db_path)`（沿用 C 阶段「每 handler 重建 `TasksStore`」模型），**不引入连接池**；跨进程靠 SQLite 文件锁（含 `BEGIN IMMEDIATE` 抢占）与 `PUBLISHING` 状态机，不靠应用层锁。

### 1.5 COMMIT 异常后的恢复合同（持久化状态未知，禁止宣称「必回 PENDING」；须处理 PUBLISHING）

> **核心约束（P0-1）**：`commit()` 抛异常后，磁盘上的持久化结果**既不可假定已提交，也不可假定已回滚——一律视为「未知」**。任何把 `COMMIT` 失败描述成「事务回滚、DB 必为 `PENDING`」的写法都是错误的，必须删除。

- **两类 commit 异常必须分开写清、不得混为「必回滚」**：
  - **(a) SQLITE_BUSY（commit 阶段）**：`COMMIT` 本身需获取写锁完成落盘；若 `busy_timeout` 内仍未取得 → 抛 `SQLITE_BUSY`。此时**几乎确定未提交**（事务仍挂在本连接），但设计上仍按「未知」处理，统一走下方恢复流程——**不得自作断言「已回滚」**。
  - **(b) 一般 I/O 类异常**（磁盘满 / `fsync` 失败 / 硬件错误 → `sqlite3.OperationalError` 或其它 `sqlite3.Error`）：`COMMIT` **可能已部分或完全落盘，也可能没有**——真实未知。
  - 二者**都进入同一恢复流程**；文档不得把任一类写成「必回 `PENDING`」。
- **恢复流程（确定性、无 sleep）**：
  1. 对本连接**尽力 `ROLLBACK`**：仅用于释放仍存活的事务、解锁；**不保证数据回归，不得把这次 rollback 当作「已证明 DB 为 PENDING」**。
  2. **关闭本连接**；若关闭抛异常或无法关闭 → 直接进入失败关闭（见第 3 步 `task-write-failed`）。
  3. 用**新连接**重新读取该 `confirmation` 的持久化状态（这是最权威的来源）：
     - 新连接读到 `APPROVED` → 返回 `unchanged` + `confirmation-already-consumed`，**不再发布**（文件可能已存在，no-replace 也不会二次写）。
      - 新连接读到 `PUBLISHING` → 进入 **`_recover_publishing` 例程**（见 §1.3）：完成发布→`APPROVED`；任何发布错误保留 `PUBLISHING` 并 `task-write-failed` 失败关闭。
     - 新连接读到 `PENDING` → 才允许后续**安全重放**（重新 `BEGIN IMMEDIATE` → … → 发布 no-replace → 条件 `UPDATE`）。
     - 新连接读取失败 / 状态不可判定 / 新连接无法建立 → `task-write-failed`，**失败关闭**。
  4. **不承诺本次无残留**（文件可能已存在、状态可能已 `APPROVED`/`PUBLISHING` 也可能仍 `PENDING`）；**不承诺自动重试一定成功**（重试同样可能再撞 `COMMIT` 异常）。调用方拿到稳定码后自行决定是否重放。

---

## 2. 发布与事务协调（崩溃残留与恢复）

### 2.1 顺序不变量（保持既有合同 + PUBLISHING 两阶段）

**文件发布成功 → 才写 `APPROVED`**，且**发布前先把 `PENDING` 持久化为 `PUBLISHING`**：
步骤：`BEGIN IMMEDIATE`（抢占写预约）→ 事务内权威重读 `status` → 仅 `PENDING` 才继续 → **阶段 1：条件 `UPDATE` 写 `PUBLISHING` + `COMMIT`（PUBLISHING 已持久）** → `BEGIN IMMEDIATE` → 仅 `PUBLISHING` 才继续 → 发布文件（no-replace）→ 成功则**阶段 2：条件 `UPDATE` 写 `APPROVED` + `COMMIT`**；发布失败保留 `PUBLISHING` 并失败关闭。过期 `EXPIRED` 转换同样在 `BEGIN IMMEDIATE` 内、受 `WHERE status='PENDING'` 守卫（见 §1.3 / P1-5）。

### 2.2 失败清理与重试

- **发布失败**（D-2 抛 `SafeWriteError` / `task-write-failed` / `task-root-unsafe`）：D-2 对外稳定错误码不携带“清理是否成功、是否无残留”的可审计证明；D-4 **一律保留 `PUBLISHING`**（不回退 `PENDING`），`task-write-failed` 失败关闭。后续仅由 `_recover_publishing` 再次通过 D-2 no-replace 发布完成 `APPROVED`；D-4 不绕过 `publish_task_file` 与句柄安全层。
- **条件 `UPDATE` 失败 / 取写预约超时**（`SQLITE_BUSY` / IO，事务未开始）：事务 `rollback`（无操作），`PENDING` 保持，映射稳定码（见 §4）。
- **`COMMIT` 失败（持写预约期间落盘失败）**：**持久化状态未知**（见 §1.5），**不得宣称「DB 回 `PENDING`」**；走 §1.5 恢复合同（尽力 rollback → 关连接 → 新连接重读：APPROVED→不发布；PUBLISHING→恢复例程；PENDING→安全重放；读失败→`task-write-failed`）。文件可能已写出；后续重放恢复（no-replace → 条件 `UPDATE` 重判），最终文件恰好一次。
- **重试语义**：仅当新连接权威重读为 `PENDING`（阶段 1 未提交且文件未发布）时，才可开始全新 approve；读到 `PUBLISHING` 只能走恢复例程；读到 `APPROVED` 直接 `already_consumed`。**不保证自动重试一定成功**。

### 2.3 崩溃恢复矩阵（**不夸大为分布式事务**）

| 崩溃点 | 残留状态 | 恢复（重放） | 文件数 |
|---|---|---|---|
| 阶段 1 提交（`PENDING→PUBLISHING`）**之前**崩溃 | 事务未提交自动回滚 → `PENDING`；**文件尚未发布** | 重新 `BEGIN IMMEDIATE` → 重读 `PENDING` → 走正常 approve 两阶段 | 0 或 1 |
| 阶段 1 已提交（`PUBLISHING` 持久）**但文件发布前/中**崩溃 | `PUBLISHING` 持久；文件可能部分/已存在 | 新 store 重读 `PUBLISHING` → `_recover_publishing`：no-replace 发布成功则 `PUBLISHING→APPROVED`；发布错误则保留 `PUBLISHING`、失败关闭；**负向终态不可写入** | 0 或 1（无半成品） |
| 发布成功后、**阶段 2 `COMMIT` 调用前**崩溃 | `PUBLISHING` 持久（阶段 1 已提交），文件已存在 | 重读 `PUBLISHING` → `_recover_publishing` 完成 `APPROVED` | 恰好 1 |
| **`COMMIT` 调用中异常**（落盘失败 / `SQLITE_BUSY`） | **持久化状态未知**；文件可能已存在 | 本连接尽力 `rollback` → 关闭 → **新连接重读权威状态**：`APPROVED`→`already_consumed`；`PUBLISHING`→`_recover_publishing`；`PENDING`→重放 | 0 或 1（no-replace 保证不多写） |
| 发布中（文件半成品 / HANDLE 未关） | `PUBLISHING`（阶段 1 已提交） | `_recover_publishing`：再次 no-replace 发布成功则完成 `APPROVED`；任何错误保留 `PUBLISHING`、`task-write-failed` | 0 或 1（无半成品） |
| 阶段 2 `COMMIT` 后、返回前 | `APPROVED`（已提交） | 重读已 `APPROVED` → `already_consumed` | 1 |

- 上述均为**单库单文件本地恢复**；**非分布式事务**，不声称跨机 / 跨卷原子性。
- 引入 `BEGIN IMMEDIATE` + 持久化 `PUBLISHING` 后：原「A 发布、B 改状态、A 才 `UPDATE`」的交错被消除；且**「文件已存在 + 负向终态」路径被 `PUBLISHING` 彻底堵死**——`reject`/`cancel`/`expiry` 读到 `PUBLISHING` 只能完成既有发布，或在失败时保持 `PUBLISHING` 并失败关闭，不得写负向。`COMMIT` 前崩溃行若发生在阶段 1 之前可合法称 `PENDING`（未提交事务自动回滚，**且文件未发布**）；阶段 1 之后残留为 `PUBLISHING`（非 `PENDING`）；`COMMIT` 中异常行**必须**称「未知」（见 §1.5）。

---

## 3. 多用户隔离（本地单 subject 模型；真实多用户 blocked）

### 3.1 与 D-3 `RuntimeIdentity` 的关系

- D-3 交付**单 subject** 身份模型：受控 `identity.json`（`version:1`）产出唯一 `subject`，经 M1「每进程一次加载」注入每个进程。
- D-4 的并发安全**在该 subject 之内**运作；**不改变 D-3 身份来源与信任边界**，也不引入多 subject。客户端 / 模型仍不能提供或覆盖 `subject` / `correlation_id` / 确认身份（D-1/D-3 不变）。

### 3.2 隔离边界（本轮实际范围）

| 对象 | 本轮隔离语义 |
|---|---|
| `subject`（确认记录 `confirmations` 表带 `subject` 列） | 每条 confirmation 绑定创建 `subject`；消费时 `_check_context` 与条件 `UPDATE` **双重断言 `subject=?`**。**同 subject 下**并发由 §1 保证唯一消费 |
| `confirmation_id` / `task_id` | `task_id` 由 `subject+correlation_id+content_hash` 派生，天然 per-subject 命名空间（不同 subject 的相同内容得到**不同** `task_id`）；`confirmation_id` 由 `task_id+content_hash` 派生 |
| 审计事件（`audit` 表） | 当前仅存 `event`/`error_code`/`task_id`/`confirmation_id`，**不存 `subject`**。本地单 subject 模型下即「**单 subject 审计**」；**跨 subject 审计隔离需为 `audit` 增加 `subject` 列（属真实多用户能力，blocked）** |
| 任务文件 | 全部落**同一 `task_root`**（程序派生 `<task_id>.json`），当前**无 per-subject 子目录**。本地单 subject 部署下是同一用户目录，不构成跨用户泄露；**真实多用户需 per-subject `task_root`（文件系统级隔离），属 blocked** |

### 3.3 真实多用户（多 subject / 多 OS 账户）= **blocked-until-approved**

- 现有本地模型**不足以安全支持真实多用户**：单一 `task_root`、audit 无 `subject` 列、身份 schema 仅 `version:1` 单 subject。要支持须：`per-subject task_root` + `audit` 增 `subject` 列 + OS 级鉴权（D-3 §9-1 / §9-3 已列 blocked）+ 真实多用户测试环境。
- D-4 **明确不实现**真实多用户；若未来做，须 `version:2` + `subjects` 表（D-3 §1.4 已预留），且**不在本轮**。
- 客户端 / 模型仍**不能提供或覆盖** `subject` / `correlation_id` / 确认身份（D-1/D-3 不变）。

---

## 4. 错误语义与审计

### 4.1 复用稳定错误码（新增码仅提案、不实现）

- **复用**（均不泄露路径/正文/异常）：`confirmation-already-consumed`、`confirmation-mismatch`、`confirmation-identity-mismatch`、`confirmation-expired`、`confirmation-required`、`confirmation-invalid-id`、`idempotency-conflict`、`task-write-failed`、`task-root-unsafe`、`invalid-arguments`。
- **提案（仅设计，本轮不实现，均为加法码，不改动既有码语义）**：
  - `database-busy`：用于 `SQLITE_BUSY`（`busy_timeout` 后仍忙）的细分。**采纳与否留待实现阶段决策**；**本轮 T4 的固定断言以复用 `task-write-failed` 为准**（COMMIT 失败路径返回 `task-write-failed`，不依赖新码）。若实现阶段采纳 `database-busy`，它是 `SQLITE_BUSY` 场景的更细分类，不改变正确性。
  - `confirmation-in-progress`：可选，表示「读到 `PUBLISHING` 且恢复例程未能立即解决（残留不可判定）→ 失败关闭」。默认实现可**直接复用 `task-write-failed`** 表达失败关闭，不强制新增此码；仅为更细语义预留。

### 4.2 审计不记录敏感信息；审计写入时机（P1-a）

- 仅存 `event` / `error_code` / `task_id` / `confirmation_id`；**不记录**路径、用户名、正文/标题/描述、密钥、Cookie、鉴权头、原始异常/堆栈。失败对外仅稳定码，绝不回显。
- **审计写入时机（修正 P1-a）**：终端动作的审计**不在会被 `ROLLBACK` 丢弃的同一事务内当作已提交事实**。规定：
  - **成功路径**：终端动作主事务（阶段 2）`COMMIT` **成功之后**，审计以**独立、best-effort 的受控事务**写入（独立连接，或同连接新起事务）；**审计写入失败不得影响已提交的终态结果、不得回滚主结果、不得泄露异常**——仅记录日志（稳定事件），对外仍返回原成功结果。
  - **回滚路径**（如输掉写预约竞争 `rowcount==0`，或发布错误后保留 `PUBLISHING`）：**不写终态审计**（或仅 best-effort 记录一次「attempt」事件，且同样独立于主回滚事务）。绝不依赖「同事务 audit 随 commit 一起落盘」的假设。
  - 简言之：**审计是「放弃即丢弃 / 独立 best-effort / 不影响主结果」的受控写入，不是主事务的组成部分**。

### 4.3 失败关闭行为

| 场景 | 行为 | 稳定码 |
|---|---|---|
| 重复批准（已 `APPROVED` 再 `approve`） | 返回 `unchanged` + `already_consumed`，不二次写 | `confirmation-already-consumed` |
| 并发冲突（双进程 `approve` 同一，败者） | 写预约串行化下败者阻塞至胜者提交后重读；胜者提交 `PUBLISHING` 后败者读 `PUBLISHING` → `_recover_publishing` → `already_consumed`，不写文件 / 不写 `APPROVED` | `confirmation-already-consumed` |
| `approve`/`reject` 竞争（一 `approve` 持写预约、另一 `reject` 被阻塞） | `approve` 阶段 1 提交 `PUBLISHING` → `reject` 重读 `PUBLISHING` → `_recover_publishing` 完成 `APPROVED` → `already_consumed`；**`reject` 绝不把 `PUBLISHING` 覆盖为 `REJECTED`** | `confirmation-already-consumed` |
| `reject`/`cancel`/`expiry` 读到 `PUBLISHING` | 走 `_recover_publishing`：完成→`APPROVED`；任意错误保留 `PUBLISHING`、失败关闭。**不得写负向终态** | `confirmation-already-consumed` / `task-write-failed` |
| 锁竞争 / 取写预约超时（`BEGIN IMMEDIATE` 阶段的 `SQLITE_BUSY`） | 事务**未开始**、无写入，可确定保持 `PENDING`；`busy_timeout` 缓解；仍忙 → `ROLLBACK`(无操作)+稳定码，可重放 | `database-busy`（提案，可选）/ `task-write-failed` |
| **`COMMIT` 中异常（落盘失败 / commit 阶段 `SQLITE_BUSY`）** | **持久化状态未知**；尽力 `rollback`→关连接→**新连接重读权威状态（含 `PUBLISHING`）**：`APPROVED`→`already_consumed`；`PUBLISHING`→`_recover_publishing`；`PENDING`→可安全重放；读失败/无法关连接→失败关闭。**不承诺无残留、不承诺重试必成** | `task-write-failed` / `database-busy`（提案，可选） |
| 发布冲突（no-replace 第二进程） | 第二进程得 `unchanged`，不二次写 | （随胜者结果） |
| 崩溃恢复（阶段 1 前崩溃） | 重放幂等，文件恰好一次，状态一致（`PENDING` 可重放，**因文件尚未发布**） | （随重放结果） |
| 崩溃恢复（阶段 1 已提交、`PUBLISHING` 残留） | `_recover_publishing` 完成，或失败关闭并保留 `PUBLISHING`，**负向终态不可写入** | （随恢复结果） |
| 崩溃恢复（COMMIT 中异常） | 见上「COMMIT 中异常」行，走 §1.5 未知恢复（含 `PUBLISHING`） | （同上） |

---

## 5. 测试与评估计划（确定性、无 sleep、无真实链接）

### 5.1 确定性并发机制与对齐点角色（**不依赖 sleep 赌时序；防死锁**）

- 用 `multiprocessing` + `Barrier` / `Event` / 共享 `Queue` 将多进程对齐到**确定性竞态窗口**，**严禁 sleep 赌时序**。
- **角色严格分离（P1-1）**：
  - **协调器（主进程）**：仅创建 worker 子进程、配置 `Barrier A` / `Event B` / `Event release_B` / 共享 `Queue`；**绝不调用 `approve`/`reject`/`cancel`**；仅通过 `Queue` **观测**中间态（不查持锁连接的 DB，避免与写锁互相阻塞）。可设**整体超时**（`Process.join(timeout)`）防卡死——超时则终止 worker 并 fail；**超时是防挂起的安全网，不是时序赌注，不得用 sleep 制造竞态**。
  - **胜者 worker**（已持写预约）：在「发布成功后、阶段 2 条件 `UPDATE` 前」**signal `Event B`** 并通过 `Queue` 报告「文件已写、`PUBLISHING` 已提交、事务仍开」；随后 **wait `release_B`**（全程持有写预约），收到后继续阶段 2 条件 `UPDATE` + `COMMIT`。
  - **败者 worker**（卡在 `BEGIN IMMEDIATE` 阻塞等锁）：**绝不是 `Event B` 的参与者**，不参与其 wait/signal；仅等写锁释放后重读（将读到 `PUBLISHING` → 恢复例程）。
  - 明确职责：**胜者 signal B + wait release_B；协调器 wait B + signal release_B；败者只等 DB 锁**。
- **对齐点 A（抢写预约）**：两 worker 都完成无锁乐观读（均见 `PENDING`）后在 `BEGIN IMMEDIATE` **之前** `Barrier A.wait()` → 二者同时抢 RESERVED，SQLite 保证**恰好一个**取得、另一个阻塞至其 commit。
- **对齐点 B（持锁内、发布后、阶段 2 条件 UPDATE 前）**：仅胜者 signal（见上）；协调器据此断言中间态（文件已存在、`PUBLISHING` 已持久、该 worker 尚未完成阶段 2）后放行。

### 5.2 覆盖矩阵

| # | 场景 | 断言要点 |
|---|---|---|
| T1 | 双进程同时 `approve` 同一 confirmation | 写预约胜者提交 `PUBLISHING`→`APPROVED` 返回 `created`、败者读 `PUBLISHING`→`_recover_publishing`→`unchanged`+`confirmation-already-consumed`；文件 1、`APPROVED` 1。**`created` 定义**：**逻辑审批提交胜者**（阶段 2 提交 `APPROVED` 成功）即 `created`，即便物理文件为 `unchanged`（可能由旧进程写出）仍 `created`；仅「之后重放已成 `APPROVED`」才 `unchanged`+`already_consumed` |
| **T2（P1-2，双确定性顺序，用 gate Event 控制先后、不靠随机抢锁/sleep）** | **T2a**：`approve` 先拿写预约并提交（阶段 1 `PUBLISHING` + 阶段 2 `APPROVED`）→ 终态 `APPROVED` + 文件存在；`reject` 后拿锁重读 `PUBLISHING` → `_recover_publishing` 完成 `APPROVED` → `already_consumed`/`mismatch`，**绝不覆盖、不写 `REJECTED`**（断言 `APPROVED` + 1 文件）。**T2b**：`reject`（或 `cancel`）先拿写预约并提交 → 终态 `REJECTED`/`CANCELLED` + 文件**不存在**；`approve` 后拿锁重读已终态 → `mismatch`/`already_consumed`，**不得发布**（断言 0 文件） |
| T3 | 同进程重复重放 `approve` | 第二次 `already_consumed`，文件仍 1 |
| T4（P0-1 + P1-1 真实竞争 + P1-c seam） | (a) **真实双进程写预约竞争**：两进程对同一 confirmation 同时 `approve`，`Barrier A` 对齐到 `BEGIN IMMEDIATE` 前（无 sleep），断言恰好一个 `created`、一个 `already_consumed`、文件 1；(b) 通过**私有连接工厂 seam / `_commit(conn)` 包装函数**注入失败（**不**直接 monkeypatch `sqlite3.Connection.commit`，因其 C 实现不可实例替换）：模拟 commit 抛 **commit 阶段 `SQLITE_BUSY`** → 固定断言返回 `task-write-failed` + 尽力 `rollback` + 关连接 + **新连接重读（含 `PUBLISHING`）**；验证恢复：读到 `APPROVED`→`already_consumed` 不发布，读到 `PUBLISHING`→`_recover_publishing`，读到 `PENDING`→安全重放；(c) 同 (b) 模拟一般 I/O `OperationalError` → 同恢复合同，断言「状态未知」被正确处置、文件可能已存在；(d) 模拟 `close`（rollback 后）抛异常 → `task-write-failed` 失败关闭 |
| **T5（P1-3 语义修正）** | **明确不是「正常并发第二进程路径」**。(a) **D-2 `publish_task_file` 单独回归**：对同 `task_id` 第二次发布得 `unchanged`，不二次写（验证 D-4 不破坏 D-2 不变量）；(b) **崩溃后恢复发布（PUBLISHING 模型）**：进程在「阶段 1 已提交 `PUBLISHING`、发布后、阶段 2 `COMMIT` 前」注入崩溃 seam（非真实并发第二进程）→ 新 store 重读 `PUBLISHING` → `_recover_publishing` → 文件 1、`APPROVED` 1（首次完成返回 `created`，即便文件 `unchanged`）。**正常并发第二进程归属 T1：它在持锁重读已 `PUBLISHING` 时走 `_recover_publishing`（no-replace 发布 + 完成 `APPROVED`），不发起一次「新 approve」流程** |
| T6 | 进程在「阶段 1 提交前 / 发布前」被杀（真实子进程终止） | 未提交事务自动回滚 → `PENDING`、文件未发布 → 新 store 重放 → 文件 0 或 1、`APPROVED` 1（与 §2.3 一致） |
| T7 | subject 隔离 | 不同 subject 消费他人 confirmation → `confirmation-identity-mismatch`，不写文件 |
| T8 | 单进程回归（保持既有） | 现有 `approve`/`reject`/`cancel`/幂等全绿 |
| **T9（本轮 P0 专用）** | **`PUBLISHING` 防负向终态**：进程 A `approve` 阶段 1 提交 `PUBLISHING` 并发布文件后、阶段 2 前被 kill；进程 B 随后 `reject`/`cancel`/`expiry` 取得写预约、读 `PUBLISHING` → 走 `_recover_publishing` 完成 `APPROVED`，或发布仍失败则保持 `PUBLISHING` + `task-write-failed`。**断言：绝不出现「文件存在 + `REJECTED`/`CANCELLED`/`EXPIRED`」组合**；成功恢复后文件 1、`APPROVED` 1。 |

### 5.3 不创建真实 symlink/junction

- 所有并发测试用临时目录 + 多进程 / 多连接；真实链接专项（D2-L1…L4）仍 skip / blocked。

### 5.4 D-6 40 例评估贡献（**不实现**）

- D-4 将贡献未来案例：并发双 `approve`（T1）、`approve`/`reject` 竞争（T2）、`PUBLISHING` 防负向终态（T9）、崩溃恢复重放（T5b/T6）、subject 隔离（T7）。D-6 仍不实现；既有 11 例 C 基线保留，新增 29 例在 D-6 补。

### 5.5 基线保留

- 保 **226 项（217 执行 + 9 skip）** 零删除；**23** 集成、**6** 入口、eval **11/11**、demo **8/8** 全保留。D-4 测试为增量。

---

## 6. 最小改动范围（供后续实现 + Codex 复核；本轮不写）

- **改 `src/mcp_notes/tasks.py`**：
  - `approve` 改为**两阶段 + `PUBLISHING`**：`BEGIN IMMEDIATE` → 权威重读 → 阶段 1 条件 `UPDATE` 写 `PUBLISHING`（守卫 `WHERE status='PENDING' AND subject=? AND correlation_id=?`，不写 `consumed_at`）→ `COMMIT` → `BEGIN IMMEDIATE` → 发布（仅此）→ 阶段 2 条件 `UPDATE` 写 `APPROVED`（守卫 `WHERE status='PUBLISHING' ...`）→ `COMMIT`；任意发布错误保留 `PUBLISHING`、失败关闭，绝不凭稳定错误码猜测无残留并回退 `PENDING`。
  - `reject`/`cancel`/`expiry`（`_terminalize`）同样 `BEGIN IMMEDIATE` → 权威重读；仅 `PENDING` 写负向；读到 `PUBLISHING` 走 `_recover_publishing`，**绝不写负向终态**。
  - 新增 `_recover_publishing` 例程（approve 乐观读、`_terminalize`、§1.5 新连接重读共用）。
  - 乐观预读**不写任何库**（不写 `EXPIRED`、不写 `audit`、不 `commit`）；连接初始化加 `busy_timeout`（仅缓解）。
  - **`COMMIT` 异常走 §1.5 恢复合同**（尽力 `rollback` → 关连接 → 新连接重读权威状态，含 `PUBLISHING`），不得宣称「DB 回 `PENDING`」；失败/commit 失败映射稳定码（不泄露异常）。
  - 审计在主事务 `COMMIT` **之后**以**独立 best-effort 事务**写入（见 §4.2），失败不影响主结果。
  - **测试 seam（P1-c）**：引入私有连接工厂 `_make_connection(db_path)` 与包装函数 `_commit(conn)` / `_close(conn)`（module 级），`TasksStore` 经此获取/提交/关闭连接；测试通过替换工厂或 patch 包装函数注入 commit/close 失败，**不**直接 monkeypatch `sqlite3.Connection` 实例方法。
- **可选新增 `database-busy` / `confirmation-in-progress` 码**（提案，不落地于设计；T4 固定断言以复用 `task-write-failed` 为准）。
- **新增 `tests/test_d4_concurrency.py`**（T1–T9，确定性 `Barrier`/`Event`/`Queue`，无 sleep、防死锁超时；含真实双进程写预约竞争 + commit 异常 seam 注入 + 关闭失败路径 + **T9 `PUBLISHING` 防负向终态**）。
- **不改**：`safe_task_write*.py`、`identity.py`、`host.py`/`server.py` 身份语义、`contracts.py`、sqlite 三表 schema（当前 `status TEXT` 无 CHECK，`PUBLISHING` 等新值无需改表；除非采纳 `audit` 增 `subject` 列——属真实多用户，blocked）。
- D-2 文件**零修改**；226/9 基线零删除。

---

## 7. 不破坏现有合同与基线

- 「文件发布成功后再写 `APPROVED`」不变量不变（§2）；且现在由 `BEGIN IMMEDIATE` 包住「发布 + 改状态」，并以前置 `PUBLISHING` 持久态消除崩溃恢复竞态。
- D-1/D-3 身份边界不变；`subject`/`correlation_id` 不可由客户端提供 / 覆盖。
- no-replace 发布、稳定错误语义、审计不存正文不变。
- 保 226/9 基线、eval 11/11、demo 8/8。

---

## 8. 仍需用户单独批准事项（blocked-until-approved）

1. **真实多用户环境**（多 OS 账户 / 多 subject / `per-subject task_root` / `audit` 增 `subject` 列）：需 D-4 实现 + 真实多用户测试环境 + `version:2` schema。
2. **真实 symlink/junction 夹具**（D2-L1…L4 及 D4 并发测试若需真实链接）：须单独批准，不创建不运行。
3. **OS 原生凭证绑定**（Windows 令牌/SID、POSIX uid）作为多用户身份附加源：D-3 §9-1 已列 blocked。
4. **跨进程身份一致性断言机制**（IPC / 共享凭据 / 启动握手）：D-3 §9-4 已列 blocked。
5. **WSL/Linux/远程 runner 真实 POSIX 验证**：沿用 D-2 blocked 口径。
6. **公开部署 / 网络传输 / 公网并发负载**：明确超出 D-4（本地单 subject 模型）。
7. **新增 `database-busy` / `confirmation-in-progress` 等错误码的最终采纳**：实现阶段再决策（T4 以复用 `task-write-failed` 为固定断言）。

D-4 可做的部分：**跨进程并发唯一消费（BEGIN IMMEDIATE 写预约 + 条件 `UPDATE` + no-replace + `PUBLISHING` 中间态）+ 本地单 subject 下的确认 / 任务文件隔离**；审计为**单 subject 审计**（当前 `audit` 表无 `subject` 列，见 §3.2），**真实跨 subject 审计隔离属 blocked（不声称已实现）**；纯本地、离线、Windows 宿主可跑。

---

## 9. 文档姿态与敏感信息约束（强制）

- 本设计为 **design-only**（规划中 / 设计完成，尚未实现）；**不得写成已实现**。
- 不公开部署，不允许公网监听；不新增网络连接（发布为本地文件写入）。
- 不把模型输出、MCP 客户端文本、环境变量中的未受控输入当作可信身份或写入授权。
- **不记录**：用户名、绝对路径、密钥、Cookie、鉴权头、环境变量值、原始异常或堆栈；审计/日志仅存稳定事件类型与稳定错误码、`task_id`/`confirmation_id` 安全标识。
- **明确否定** WAL / 连接池 / Python 锁作为跨进程并发安全方案（§1.2）。
- **明确真实多用户为 blocked**，不声称已实现（§3.3）。
- **明确非分布式事务**，不声称跨机 / 跨卷原子性（§2.3）。
- 部署前提必须与代码同时成立：受控身份根客户端不可写；否则该部署不在 D-3 信任模型内。

---

## 10. 复核修订记录

- **v1（2026-08-08）**：初版设计包。分支 `codex/p3-local-mcp-tool-service`，HEAD `b9fdff8`。**仅设计与文档，不写代码、不装依赖、不暂存、不提交、不 push、不建 PR**，等待 Codex 设计复核。设计范围：并发确认消费用事务条件更新（§1）、发布与事务协调（§2）、多用户隔离边界与真实多用户 blocked（§3）、错误语义与审计（§4）、确定性并发测试计划（§5）。新增 `docs/D-4-design.md`；更新 `DECISIONS.md`（D-028）、`docs/PRD.md`（§10/§11.2）、`docs/ARCHITECTURE.md`（§7）、`STATUS.md`（D-4 设计阶段条目）。
- **v1 第一轮修正（2026-08-08，Codex 设计复核结论 NEEDS-FIX → 已修正，待再审）**：Codex 指出 P0 并发设计漏洞——原 `approve`「先发布、后条件 `UPDATE`」在 `BEGIN IMMEDIATE` 之外，存在交错「A 发布文件、B 把状态改 `REJECTED`、A 才条件 `UPDATE`（`rowcount==0`）」→ 文件存在但 DB 为 `REJECTED`。修正：所有终态动作在读状态前 `BEGIN IMMEDIATE` 抢占写预约、同一事务内完成「权威重读 → 发布（仅 approve）→ 条件 `UPDATE` → idempotency/audit → `COMMIT`」，彻底串行化；保留 `WHERE status='PENDING'` + `rowcount` 纵深。仍 design-only、未提交、未 push、未建 PR，待 Codex 再审。
- **v1 第二轮修正（2026-08-08，据用户更严格反馈 + 独立反向安全审计 → 已修正，待 Codex 集中复核）**：**P0-1**：删除所有「`COMMIT` 失败 → 事务回滚、DB 必回 `PENDING`」的错误断言。新增 **§1.5 恢复合同**：`commit()` 异常后持久化状态**视为未知**；区分 commit 阶段 `SQLITE_BUSY` 与一般 I/O 异常；恢复 = 尽力 `rollback` → 关连接 → **新连接重读权威状态**（APPROVED→不发布；PENDING→安全重放；读失败→`task-write-failed`）。**P1-1/2/3/4/5**：对齐点角色防死锁、T2 双确定性顺序、T5 语义纠偏、过期事务守卫、审计表述修正。逐项反向审计无矛盾。仍 design-only、未提交、未 push、未建 PR，待 Codex 集中复核。
- **v1 第三轮修正（2026-08-09，Codex 集中复核结论 NEEDS-FIX → 已修正，待 Codex 最终复核 / 接力实现）**：
  - **P0（崩溃恢复竞态，本轮核心）**：原设计在 `BEGIN IMMEDIATE` 内「发布 + 条件 `UPDATE`」仍可被崩溃恢复竞态击穿——A 发布后、`COMMIT` 前崩溃回滚为 `PENDING`（文件已存在），随后 B `reject`/`cancel`/`expiry` 读 `PENDING` 写负向终态 → 又成「文件存在 + 负向终态」。修正：引入**持久化 `PUBLISHING` 中间态**（状态机 `PENDING → PUBLISHING`（阶段 1 提交，发布前）→ `APPROVED`（阶段 2 提交，文件成功后））。`reject`/`cancel`/`expiry` 读到 `PUBLISHING` **不得写负向终态**，必须走 `_recover_publishing` 完成既有发布；任意发布错误保留 `PUBLISHING`、失败关闭。§1.2 增 `PUBLISHING` 为第 4 层纵深；§1.3 重写为两阶段算法 + `_recover_publishing`；§1.5 新连接重读增 `PUBLISHING` 分支；§2.1/§2.2/§2.3 全面纳入 `PUBLISHING`；§4.3 增 `PUBLISHING` 失败关闭行；§5.2 增 **T9（`PUBLISHING` 防负向终态）**；§6 最小改动范围同步。
  - **P1-a（audit/rollback）**：§4.2 明确审计**不在会被 `ROLLBACK` 丢弃的同一事务内当作已提交事实**——成功路径在主事务 `COMMIT` 之后以**独立 best-effort 事务**写入、失败不影响主结果；回滚路径不写终态审计。
  - **P1-b（文件创建者表述）**：§1.3 / T1 的 `created` 定义改为「**逻辑审批提交胜者**」，删除「文件创建者与 SQL 胜者同一进程」的误导表述（崩溃恢复时物理文件可来自旧进程）。
  - **P1-c（测试 seam）**：§5.2 T4 / §6 改为**私有连接工厂 `_make_connection` + 包装函数 `_commit(conn)`/`_close(conn)`** 作为测试 seam；**不**直接 monkeypatch `sqlite3.Connection.commit/close`（C 实现不可实例替换）。
  - **database-busy 采纳**：§4.1 / T4 固定断言——COMMIT 失败路径复用 `task-write-failed`；`database-busy` 仍属可选加法码，实现阶段决策，不阻塞 D-4。可选 `confirmation-in-progress` 同理（默认复用 `task-write-failed`）。
  - **高层文档同步**：`STATUS.md` / `ARCHITECTURE.md` / `DECISIONS.md` 中「`PENDING` 一律可重放」的高层表述改为「`PENDING` 仅在文件尚未发布时安全重放；文件已存在时须按 `PUBLISHING` 契约完成既有发布，失败则保持 `PUBLISHING`，不得写负向终态」（见对应文件本轮修改 + D-028 第三轮修正段）。
  - 仍 **design-only、未暂存、未提交、未 push、未建 PR**，待 Codex 最终复核；用户已决定：本轮修正后**将本地 MCP 工具服务项目后续全部开发交 Codex 接力**（见 `docs/HANDOFF-TO-CODEX.md`）。
