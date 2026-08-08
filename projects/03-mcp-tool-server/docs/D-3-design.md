# D-3 详细设计：唯一身份来源与信任边界（设计包 v3）

> 状态：**D-3 实现已由本地提交 `d14341d` 落地（未 push、未建 PR；本次 Codex 复核中）**；本文件为 **D-3 设计包 v3（design-only 内容为实现前历史记录，保留以示设计来源）**。
> **（以下为实现前 design-only 历史姿态，约束精神仍适用）** 不公开部署、不允许公网监听；不新增任何网络连接（身份加载仅为本地文件读取）；不把模型输出、MCP 客户端文本、环境变量中的未受控输入当作可信身份；不记录用户名、绝对路径、密钥、Cookie、鉴权头或原始异常。
> 相对 D-1（`subject` 已实现精确字符白名单 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`、缺失/非法在配置启动失败关闭）与 D-2（跨平台原子发布一致性），D-3 **只回答「唯一可信 subject 来源是谁、信任边界在哪、缺失/不可用如何失败关闭」**，不触碰发布核心、sqlite 状态机与 D-1 字符白名单。
> 分支：`codex/p3-local-mcp-tool-service`（注意：不是 `...tool-server`）。基线 HEAD：`09038cd`。

**v3 修订说明（针对 v2 的 Codex 复核结论「需修改，2 个 P0 + 3 个 P1」）**

| 编号 | v2 问题 | v3 修正 | 落点 |
|---|---|---|---|
| P0-1 | 「单进程 + 同一 `RuntimeIdentity` 实例」与现有 C 阶段 stdio 演示冲突：演示先 spawn 独立 Server 子进程（`demo/mcp_stdio_demo.py:85`）、再在父进程构造 Host（`demo/mcp_stdio_demo.py:126`），两进程不可能共享同一 Python 对象，v2 却同时承诺演示保持 8/8 | **按 Codex 推荐方案 1 写死**：D-3 采用 **「每进程一次加载」模型（M1）**，**支持现有分离进程演示**。**删除「同一对象实例」「每进程一次即可证明一致」的表述**：每个进程在自身 bootstrap 处各自安全读取**同一个**受控身份文件；一致性来源改述为「同一受控文件 + 确定性加载算法 → 同值」，**不是**对象同一性。单进程内嵌（tests/evals）是 M1 的特例，不是独立模型 | §5.1、§5.2、§2 |
| P0-2 | 测试矩阵自相矛盾：§5 要求「同一实例、每进程一次、禁绕过加载器」，测试 24 却要构造「不同 `RuntimeIdentity`」 | 先由 P0-1 定死进程模型，再把测试 24 改为该模型**真实允许**的路径：**两次独立调用真实加载器**、分别读取**两个不同的受控身份根**（模拟两个进程各自加载），全程不绕过加载器。同时明确「每进程一次」是**生产 bootstrap 入口的约束**，不是加载器的技术限制——加载器无全局状态、可重入，受信的测试/演示可多次调用以模拟多进程 | §5.3、§7.2 D |
| P1-1 | 「私有哨兵」被写成安全边界；实际上同进程内代码仍可访问私有成员或直接构造 | 收紧表述：私有哨兵**仅为受信代码内的类型/API 防呆**，**不是安全边界**、**不证明「只能由加载器产出」**。真正边界是 **MCP 客户端/模型无法在服务进程内执行代码**、无法写受控身份根、无法控制受控启动器环境 | §5.4、§7.2 D-22 |
| P1-2 | 「Host 所有启动入口只输出稳定码」不可验收：`host.py` 是库类，无 `main()`、无已定义启动入口（`host.py:39`） | 删除该全称承诺。改为：DoD 只约束**现存且可测**的两类入口——`server.main()`（已实现稳定码路径，`server.py:376-378`）与**受控启动器**（demo / evals / 测试夹具）；`host.py` **本轮不新增 `main()`**；另立**前瞻性约束条款**：未来若新增 Host 启动入口，必须捕获并仅输出稳定码 | §3、§7.2 E、§7.4 |
| P1-3 | `ARCHITECTURE.md:81`、`PRD.md:128` 仍指向已 superseded 的 D-025 | 两处引用改为 **D-027 / v3**，并显式标注 D-025（v1）、D-026（v2）为历史 | 文档同步 |

**Codex 已判定闭环、v3 保持不变的部分**（不得在 v3 中回退）：① `MCP_NOTES_SUBJECT` 仅作文件读取后的相等性断言、不再后备产生 subject；② `identity.json` schema、4096 B 上限、UTF-8 无 BOM、未知字段拒绝；③ fd/HANDLE 链读取、对已打开对象 `fstat`、能力缺失失败关闭、identity 边界映射 `invalid-arguments`，且不改 D-2 对外语义；④ D-025 已正确标为 superseded、D-026 为其时决策（本轮起以 D-027 为当前决策）；⑤ `create_task` 仅接受 `title`/`description`（形状守卫 `server.py:231`）；⑥ Host 用自身 subject + 存储 `correlation_id` 重建上下文（`host.py:41`）；⑦ `correlation_id` 服务端派生 64-hex 未改动。

<details>
<summary><b>v2 修订说明（历史，针对 v1 的 3 个 P0；本表所列修正在 v3 中全部保留）</b></summary>

| 编号 | v1 问题 | v2 修正（v3 保留） |
|---|---|---|
| P0-1 | `MCP_NOTES_SUBJECT` 仍是第二个权威来源（文件缺失时作后备） | 身份文件必须存在；env 永不产生最终 subject，仅作可选相等性断言 |
| P0-2 | 身份文件「安全读取」无可实施算法 | 受控身份根 + fd/HANDLE 链读取算法（复用 D-2 原语） |
| P0-3 | Server/Host「启动期一致性断言」在分离进程下无法实现 | 取消该断言；**注**：v2 由此收敛到「单进程唯一模式」，该收敛已被 v3 的 P0-1 修正为「每进程一次加载、支持分离进程」 |
| P1-1 | `identity.json` schema 不完整 | 完整 schema（见 §1.4） |
| P1-2 | `MCP_NOTES_IDENTITY_FILE` 路径来源未约束 | 只能来自受控启动器；客户端可控整个环境则不在信任模型内 |
| P1-3 | `identity-unavailable` 去留未定 | 不新增，复用 `invalid-arguments` |

</details>

---

## 0. 范围与门面确认

- D-3 收敛在**身份来源与信任边界**，不进入 D-4（并发/多用户隔离）、D-5（传输扩展）、D-6（评估补齐）；不创建/运行真实 symlink/junction；不调用模型、不联网、不引入依赖。
- 现有身份相关代码点（已实现，D-3 设计须与之兼容、不得回退）：
  - `src/mcp_notes/server.py`：`ServerConfig.from_env()` 读 `MCP_NOTES_SUBJECT`（必填、无默认）、构造期 `__post_init__` 调 `_valid_subject` 失败关闭；`create_task_tool` 仅派 `correlation_id`、用 `config.subject` 构造 `TrustedContext`。
  - `src/mcp_notes/host.py`：`TrustedHostController.__init__` 校验 `self._subject`；`_rebuild_context` 用 `self._subject` + `store.lookup_correlation_id` 重建 `TrustedContext`，**绝不用记录中的 subject**。
  - `src/mcp_notes/contracts.py` / `tasks.py`：`_valid_subject` / `_valid_correlation_id` 与 `TrustedContext.__init__`，D-1 已强制（D-3 不改）。
  - `src/mcp_notes/safe_task_write.py` / `safe_task_write_posix.py`：D-2 已验证的**受控目录链打开原语**，D-3 **只读复用、零修改**（见 §1.3）。
- D-3 设计目标：把「subject 从哪来、谁可信、失败如何关闭」从当前的「环境变量或进程凭证二选一（未决）」收敛为**单一可审计来源 + 明确信任边界 + 稳定失败关闭**。

---

## 1. 唯一可信 subject 来源（核心决定；v2 已修 P0-1 / P0-2 / P1-1 / P1-2，**Codex 已判闭环，v3 不改**）

### 1.1 决定（单一权威值来源）

**唯一权威来源 = 受控身份根下、由可信本地部署操作者带外预置的 `identity.json`。该文件必须存在且必须通过安全读取；文件是最终 `subject` 值的唯一产出方。**

**`MCP_NOTES_SUBJECT` 不再是任何意义上的值来源**：

- 它**永不产生**最终 subject；文件缺失时**不作后备**——文件缺失即失败关闭。
- 它只保留一个可选用途：**相等性断言（equality assertion）**。仅当身份文件已被安全读取并产出 `subject` 之后，若 env 同时给出该变量，则必须 `env_value == file_subject`；不等 → 失败关闭。env 未给出 → 忽略，不影响结果。
- 该退化是**可验证的不变量**（写入测试矩阵）：

  > **等价不变量（P0-1 验收断言）**：对任意环境，删除 `MCP_NOTES_SUBJECT` 后再次加载，若原先加载成功，则结果必须**逐字节相同**；env 对最终值的贡献恒为零。

**理由（为何必须这样收紧）**：在 MCP stdio 模型下，若客户端能控制 Server 的 spawn，它就能控制被继承的进程环境。因此环境变量**不能承载值**，只能承载一个「与已受控来源比对」的断言。`load_subject()` 是单一函数不等于单一权威来源——权威性由「值只能来自受控文件」保证，而非由「只有一个函数」保证。

### 1.2 受控身份根（controlled identity root）与路径约束

- 新增部署配置 `MCP_NOTES_IDENTITY_FILE`，形如 `<identity_dir>/<name>`；缺省 `<state_dir>/identity.json`（与 `control.db` 共置）。
- **`<identity_dir>`（受控身份根）必须由可信部署带外预置，且 MCP 客户端/模型不可写**。生产代码**绝不创建**该目录或该文件（与 `task_root` 的既有「部署配置预存在」模式一致）。
- **`<name>` 约束**：必须是单个路径组件，匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.json$`；不得包含路径分隔符、`..`、`\x00`、驱动器前缀或 UNC 前缀。不满足 → 失败关闭。
- **`MCP_NOTES_IDENTITY_FILE` 这个路径本身只能来自受控启动器**（可信部署操作者控制的启动脚本 / 服务定义 / 计划任务）。
  > **信任模型边界声明（P1-2）**：若 MCP 客户端能够控制服务进程的**整个环境**（env、工作目录、启动参数），则该部署**不在 D-3 的信任模型之内**，D-3 不为其提供任何身份保证，也**不得声称**其受保护。这是部署前提，不是代码可弥补的缺口。

### 1.3 身份文件安全读取算法（P0-2：可实施、防链接跟随、防检查后替换）

核心原则三条：**① 绝不按字符串路径读取；② 先打开、再基于同一 fd/HANDLE 做类型断言与读取（身份由句柄固定，不由路径固定）；③ 能力缺失即失败关闭，绝无字符串路径回退。**

复用 D-2 **已实现并已通过 Codex 复核**的原语，**不修改 `safe_task_write*.py` 任何一行**（只读、跨模块调用；POSIX 侧为包内内部复用）：

**步骤 A — 拆分与校验**
1. 把 `MCP_NOTES_IDENTITY_FILE` 拆为 `<identity_dir>` 与 `<name>`；按 §1.2 校验 `<name>`。
2. `<identity_dir>` 为绝对路径；含 `\x00` 组件 → 失败关闭。

**步骤 B — 打开受控身份根，得到已验证父句柄**
- **Windows**：调 `safe_task_write.open_task_root(<identity_dir>)` → 从盘符根起逐级 `OBJ_DONT_REPARSE` 打开，返回已验证目录 HANDLE 链；任一级为 reparse point（symlink/junction）、根字符串非法、原生 API 不可用 → `SafeWriteError(task-root-unsafe)`。
- **POSIX**：先 `safe_task_write_posix._posix_supported()`（校验 `dir_fd` / `O_NOFOLLOW` / `O_DIRECTORY` / `fstat` / `fsync` 能力）；不支持 → 失败关闭。再 `_open_root(<identity_dir>)` → 从 `/` 的目录 fd 起逐级 `os.open(O_RDONLY|O_DIRECTORY|O_NOFOLLOW, dir_fd=parent)` + `fstat` 断言目录，返回已验证 fd 链。
- 两侧均由调用方负责在 `finally` 中精确关闭句柄/fd 链（关闭失败不覆盖已确定的稳定码、不泄露原始异常）。

**步骤 C — 相对已验证父句柄打开身份文件（拒绝链接跟随）**
- **Windows**：`safe_task_write._nt_open(parent_handle, <name>, is_dir=False)`（`OBJ_DONT_REPARSE`），reparse / 路径逃逸 / IO / 非普通文件 → 失败关闭；再 `msvcrt.open_osfhandle(..., O_RDONLY|O_BINARY)` 转 fd 读取。
- **POSIX**：`os.open(<name>, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)`；`ELOOP`（仍为 symlink）/ `FileNotFoundError` → 失败关闭。

**步骤 D — 基于已打开 fd 做类型断言（防「检查后替换」TOCTOU）**
- 对**已打开的 fd** 执行 `os.fstat(fd)`，要求 `stat.S_ISREG` 为真；目录/FIFO/字符设备/块设备/socket/symlink/无法归类 → 失败关闭。
- **关键**：断言对象是 fd 指向的实际对象，不是路径。攻击者在打开后替换路径上的条目，不会改变已打开 fd 的身份；因此不存在「stat 通过 → 路径被换 → 读到别的文件」的窗口。
- 明令禁止的反模式：`os.path.exists` / `os.stat(path)` / `os.path.realpath` 作为安全判断后再按路径 `open()`；`realpath` 不是路径安全权威（沿用 D-2 收紧结论）。

**步骤 E — 限长读取与解析**
- 从同一 fd 循环读取，**最多读 `MAX_IDENTITY_BYTES + 1 = 4097` 字节**；一旦超过 4096 → 失败关闭（防超大/无穷文件占用与内存放大）。
- UTF-8 解码（不接受 BOM）→ `json.loads`；解码或解析失败 → 失败关闭。
- 按 §1.4 schema 严格校验。

**步骤 F — 错误映射与无泄露**
- D-2 原语抛出的 `SafeWriteError(task-root-unsafe | task-write-failed)` 在 identity 模块边界**统一映射**为 `TaskPublishError(INVALID_ARGUMENTS)`；**绝不上抛原始 `OSError` / 系统细节 / 路径 / 用户名**。
- 该映射只发生在 D-3 新模块内部，**不改变 D-2 对外错误语义**（发布路径仍返回其原有稳定码）。

### 1.4 `identity.json` 完整 schema（P1-1）

```json
{
  "version": 1,
  "subject": "local-notes-operator",
  "subject_kind": "deployment-provisioned"
}
```

| 项 | 规则 | 违反后果 |
|---|---|---|
| 顶层类型 | 必须是 JSON object（`dict`） | 失败关闭 |
| `version` | **必填**；类型必须是 `int`（显式拒绝 `bool`，因 `bool` 是 `int` 子类）；值必须 `== 1` | 失败关闭 |
| `subject` | **必填**；类型 `str`；必须匹配 D-1 白名单 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`（长度 1..128） | 失败关闭 |
| `subject_kind` | **必填**；类型 `str`；允许值**仅** `"deployment-provisioned"`（v1 唯一合法值） | 失败关闭 |
| 未知键 | **严格拒绝**：出现任何上述三键之外的顶层键即失败关闭 | 失败关闭 |
| 最大文件大小 | `MAX_IDENTITY_BYTES = 4096` 字节（读到第 4097 字节即判超限） | 失败关闭 |
| 编码 | UTF-8，不接受 BOM、不接受非 UTF-8 字节序列 | 失败关闭 |

- **为何未知键严格拒绝**：宽松忽略会造成「以为写了配置、实际被无视」的安全错觉（例如误以为写入了 `allowed_subjects` 就生效）。向前兼容改由 `version` 递增承担。
- `subject_kind` 只作审计标注，**不进入授权判定**（当前唯一合法值即唯一形态）。
- **未来多用户**（D-4 及以后）将以 `version: 2` + `subjects: [...]` 表承载；**D-3 不实现、不解析、不声称支持**——遇到 `version != 1` 一律失败关闭。

### 1.5 候选来源取舍

| 候选来源 | 结论 | 理由 |
|---|---|---|
| 受控身份根下的部署预置身份文件（**采纳，唯一值来源**） | 单一权威来源 | 跨平台（仅一个本地路径）；由可信部署操作者带外写入，MCP 客户端/模型无写入或注入路径；可审计、可离线测试；可用 D-2 已验证的 fd/HANDLE 链安全读取；未来可经 `version` 递增扩展多用户；与 `task_root`/`notes_root` 的「部署配置预存在」模式一致；纯本地文件读取，无网络、无原生凭证 API 硬依赖。 |
| 环境变量 `MCP_NOTES_SUBJECT` | **非权威；降级为可选相等性断言，永不产生值** | env 由父进程继承；MCP stdio 模型下客户端若控制 spawn 即可注入；不可审计、不可完整性校验、无法承载 schema。**不可作为后备**（v1 的 P0-1）。 |
| OS 进程/用户凭证（Windows 令牌 SID、POSIX uid） | 推迟（blocked-until-approved） | 最「不可伪造」，但平台分裂、需原生 API（部分平台不可用，破坏「无硬原生凭证依赖」目标）、绑定 OS 登录、无法用离线虚构夹具完整测试。 |
| 签名清单 / 双向 TLS / PKI | 推迟（blocked-until-approved） | 需密钥材料与密钥管理，与「仓库不放密钥、最小依赖、不联网」冲突；属公开部署议题。 |

---

## 2. 信任边界：谁设置、谁修改、为何客户端/模型不能伪造

- **谁断言 subject**：可信本地部署操作者，通过带外写入受控身份根下的 `identity.json` 完成。断言发生在服务处理任何请求**之前**。**设置 `MCP_NOTES_SUBJECT` 不构成断言**（它不产生值）。
- **谁可以修改 subject**：仅对受控身份根具有写权限的部署操作者。**MCP 客户端、模型、笔记正文、任何 Tool/请求字段都没有 subject 的写路径或注入路径。**
- **为何客户端/模型无法伪造或覆盖**：
  1. `subject` 从来不是 Tool 参数：`create_task` 只接受 `title`/`description`（`_TOOL_ARG_SPEC` 形状守卫 + `SafeMCPServer` 拦截拒绝未知字段，`server.py:231`）；`notes://service-info` 只说明身份派生方式，不接收身份。
  2. `correlation_id` 是服务端派生（见 §4），不是 subject、不是凭证。
  3. Host 的 subject 与 Server 的 subject 同源于**同一个受控身份文件**（各自进程在 bootstrap 期经 `load_runtime_identity()` 读取，见 §5），**绝不来自持久化记录中的 subject**——记录只存 `subject+correlation_id` 的哈希用于幂等/身份匹配。`_rebuild_context` 用 `self._subject`（`host.py:41`）。
  4. 值只能由受控身份根下的文件产出；env 只能「同意或否决」，不能「提供」。
  5. 每个进程内的 subject 只有一个，就是该进程 bootstrap 期加载的那一个；任何通过请求提供身份的路径在结构上不存在。
- **信任边界落点**：受控身份根及其部署配置路径属于「本地可信部署边界」，与 `task_root`/`notes_root` 同源可信；MCP 客户端/模型属于「不可信数据边界」，仅能提供 `title`/`description` 与搜索关键词。
- **边界之外**：若客户端可控制整个进程环境（含 `MCP_NOTES_IDENTITY_FILE` 指向何处），该部署不在 D-3 信任模型内（§1.2）。

---

## 3. 启动期失败：稳定码与无泄露（v2 已按 P0-1 / P0-3 / P1-3 修正；v3 按本轮 P1-2 收紧「入口」范围）

所有失败均在**进程 bootstrap 加载期**发生，早于任何 Tool 调用；统一失败关闭、绝不回退默认主体、绝不泄露路径/正文/用户名/异常。

| 情形 | 行为 | 稳定码 |
|---|---|---|
| 身份文件缺失（**无论 `MCP_NOTES_SUBJECT` 是否给出**） | 启动失败关闭，无默认主体，**env 不作后备** | `invalid-arguments` |
| `MCP_NOTES_IDENTITY_FILE` 未配置且缺省路径下无文件 | 启动失败关闭 | `invalid-arguments` |
| `<name>` 不符 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.json$` / 含分隔符 / `..` / `\x00` / UNC / 驱动器前缀 | 启动失败关闭 | `invalid-arguments` |
| 身份根或其任一祖先为 reparse point / symlink / junction；或身份文件本身为 symlink / reparse | 启动失败关闭（步骤 B/C 拒绝） | `invalid-arguments` |
| 身份文件非普通文件（目录/FIFO/设备/socket）；或打开前后类型不一致 | 启动失败关闭（步骤 D `fstat` 断言） | `invalid-arguments` |
| 平台能力缺失（POSIX 无 `O_NOFOLLOW`/`O_DIRECTORY`/`dir_fd`/`fstat`；Windows 原生 API 不可用） | 启动失败关闭，**绝无字符串路径回退** | `invalid-arguments` |
| 权限拒绝 / 读取 IO 失败 | 启动失败关闭 | `invalid-arguments` |
| 文件超过 4096 字节 | 启动失败关闭 | `invalid-arguments` |
| 非 UTF-8 / 带 BOM / JSON 解析失败 / 顶层非 object | 启动失败关闭 | `invalid-arguments` |
| `version` 缺失 / 非 `int` / 为 `bool` / `!= 1` | 启动失败关闭 | `invalid-arguments` |
| `subject` 缺失 / 非 `str` / 空 / 不符 D-1 白名单或长度越界 | 启动失败关闭 | `invalid-arguments` |
| `subject_kind` 缺失 / 非 `str` / 非 `"deployment-provisioned"` | 启动失败关闭 | `invalid-arguments` |
| 出现任何未知顶层键 | 启动失败关闭 | `invalid-arguments` |
| `MCP_NOTES_SUBJECT` 给出且 `!= file_subject`（相等性断言失败） | 启动失败关闭 | `invalid-arguments` |

> **已删除（v1 的 P0-3，v3 仍保持删除）**：v1 表中「Server 与 Host 启动时加载的 subject 不一致 → 启动期一致性断言失败关闭」一行**已移除**。理由见 §5.2：分离进程下该断言无通道、且两次读取之间文件可变，无法实现。
> **v3 补充**：v2 曾试图用「单进程唯一模式」在架构上消灭该场景，但那与现有分离进程演示冲突（本轮 P0-1）。v3 改为**承认该场景存在**（M1 支持分离进程），**不在启动期断言**，把跨进程偏差的处理明确留给请求期 `confirmation-identity-mismatch`——即：不消灭场景，也不虚称能断言，而是如实标注保护范围（§5.1 已知限制）。

**稳定码决定（P1-3）**：**不新增 `identity-unavailable`**。全部身份失败复用 `invalid-arguments`，理由是对外信息更少（不区分「配置缺失」与「来源被攻击」，避免探测），且严格保持 D-1/D-2 已冻结合同不被扩大。

> **该决定的强制前提（v3 已按本轮 P1-2 改为可验收范围）**：
>
> **v2 的表述「Server 与 Host 的所有启动入口」不可验收并已删除**——`host.py` 是库类（`host.py:39`），**没有 `main()`、没有任何已定义的启动入口**，「所有 Host 启动入口」是一个空集合上的全称承诺，无法写出对应测试。
>
> v3 把前提收紧为**当前真实存在、且可用 subprocess 断言**的两类入口：
>
> 1. **`server.main()`**（`src/mcp_notes/server.py:358`）：已实现 `except TaskPublishError → sys.stderr.write("invalid-arguments\n"); sys.exit(2)`（`server.py:376-378`，D-1 P0-2 成果）。D-3 新增的身份加载失败必须走同一路径。
> 2. **受控启动器**（Host 侧当前唯一的实际启动路径）：`demo/mcp_stdio_demo.py`、`evals/run_c_phase_eval.py` 与测试夹具——它们在构造 `TrustedHostController` 之前调用加载器。身份加载失败时同样要求 `stdout` 空、`stderr` 仅稳定码、非零退出。
>
> 具体要求（两类入口一致）：任何 bootstrap 失败路径仅向 `stderr` 输出稳定码字符串、`stdout` 保持空、以非零码退出；禁止 `str(e)` / traceback / 绝对路径 / 用户名 / 环境变量值 / Cookie / 鉴权头。
>
> **本轮明确不做**：不为 `host.py` 新增 `main()` / CLI（D-3 不扩大实现面）。
>
> **前瞻性约束条款（非本轮 DoD 可验收项，写入以免未来失守）**：今后若为 Host 新增任何启动入口（CLI、服务包装器、计划任务脚本），该入口**必须**捕获 `TaskPublishError` 并仅输出稳定码、非零退出，并同时补上等价的 subprocess 断言；在该入口出现之前，D-3 **不声称**「Host 所有启动入口已满足稳定码要求」。

---

## 4. correlation_id 保持服务端确定性派生（不是身份凭证）

- 维持 `server._derive_correlation_id(title, description)` = `SHA-256(NFKC(title) + "\x1f" + NFKC(description)).hexdigest()`，64 位小写十六进制，**由服务端按规范化请求内容本地派生**。
- **客户端永远不能直接提供或覆盖 `correlation_id`**：它不是 Tool 参数；Host 仅从 `TasksStore.lookup_correlation_id(confirmation_id)` 取回。
- **它不是凭证、不授予批准权限**：仅把一次请求绑定到一条记录，用于重放幂等（`task_id`/`confirmation_id` 稳定）与身份匹配（与 subject 共同相等才消费）；批准仍要求 Tool 外本地 Host、Host 自身受控 subject 与记录匹配。
- D-3 **不改变** `correlation_id` 的派生方式与格式；仅明确其身份语义：「相关但不等同」——`correlation_id` 是请求级绑定标识，`subject` 才是身份主体。
- （未来可选，非 D-3）若需更紧绑定，可让派生命名空间包含 `subject`；当前不要求、不实现。

---

## 5. 进程模型与身份绑定（v3 已按本轮 P0-1 / P0-2 / P1-1 重写）

### 5.1 采纳模型 M1：每进程一次加载（D-3 唯一模型，**支持现有分离进程演示**）

> **为什么改**：v2 写死「单进程 + Server/Host 共享同一 `RuntimeIdentity` 对象实例」，与 C 阶段已完成的 stdio 演示直接冲突——演示以 `StdioServerParameters(command=sys.executable, args=["-m", "mcp_notes.server"], ...)` **spawn 独立 Server 子进程**（`demo/mcp_stdio_demo.py:83-88`），随后在**父进程**构造 `TrustedHostController`（`demo/mcp_stdio_demo.py:126`）。两个操作系统进程之间不可能共享同一个 Python 对象，而 v2 同时承诺演示保持 8/8，属于自相矛盾。v3 按 Codex 推荐的方案 1 修正，**保住已完成的 C 演示**。

**M1 定义**

- 加载器 `load_runtime_identity(environ, identity_file_path) -> RuntimeIdentity` 是**无全局状态、可重入的纯加载函数**：每次调用都完整执行 §1.2 路径校验 → §1.3 fd/HANDLE 链安全读取 → §1.4 schema 校验 → §1.1 env 相等性断言。它**不缓存**、**不设进程级单例变量**。
- **每个参与进程在自身 bootstrap 处调用它恰好一次**，得到该进程唯一的 `RuntimeIdentity`，注入本进程内的组件：

  | 进程 | bootstrap 位置 | 注入对象 |
  |---|---|---|
  | Server 子进程（`python -m mcp_notes.server`） | `ServerConfig.from_env()` | `ServerConfig` |
  | Host 侧受控启动器进程（demo / evals / 测试夹具） | 构造 Host 之前 | `TrustedHostController` |
  | 单进程内嵌（tests / evals 把二者放同一进程） | 该进程唯一 bootstrap | 同时注入两者（**M1 的特例，不是独立模型**） |

- **生产构造器不再接受裸 `subject: str`**：`TrustedHostController.__init__(db_path, task_root, identity: RuntimeIdentity, clock=None)`；传入 `str` 或非 `RuntimeIdentity` → `TaskPublishError(INVALID_ARGUMENTS)` 失败关闭。`ServerConfig` 同理持有 `RuntimeIdentity`。
- **「每进程一次」是生产 bootstrap 入口的约束，不是加载器的技术限制**。受信代码（测试、演示、评估脚本）可以多次调用加载器，用于**模拟多个进程各自加载**——每次调用仍走完整安全读取，**不存在绕过加载器的路径**。这一条是 §7.2 测试 24 得以成立的前提（本轮 P0-2）。

**一致性来源（v3 改述，不再声称对象同一性）**

- v2 的说法「同一对象实例 ⇒ 一致」**已删除**：在 M1 下 Server 与 Host 通常位于不同进程，各持各自的 `RuntimeIdentity` 对象。
- v3 的真实保证是：**同一个受控身份文件 + 确定性加载算法 ⇒ 同一个 `subject` 值**。这是一个部署级保证（依赖「两个进程被指向同一个受控身份文件」这一部署前提），不是密码学保证，也不是对象同一性保证。
- **已知限制（不虚称）**：若两个进程被指向**不同**的受控身份文件，或有权限的部署操作者在两次加载之间修改了文件，则两进程的 `subject` 可能不同。**D-3 在启动期检测不到这种偏差**（见 §5.2），此时唯一的保护是请求期失败关闭 `confirmation-identity-mismatch`（见 §5.2 第 2 段）。

### 5.2 明确不支持：跨进程的「启动期一致性断言」

- **D-3 明确不支持**跨进程的启动期 subject 一致性断言（此结论自 v2 起未变，Codex 已认可）。理由：
  1. 现有 `host.py` 与 Server 之间**没有身份比较通道**（Host 是 Tool 之外的本地控制器，不与 Server 进程通信）；
  2. D-3 **零网络**、不引入 IPC，无法在启动期交换并比对身份；
  3. 即使各自读取同一文件，两次读取之间文件可变，「启动期断言」也无法给出跨进程的真实保证——声称能做即为虚称。
- 分离进程下的实际保护**仅有既有请求期失败关闭**：`TasksStore._check_context` 断言提供 subject == 创建意图 subject（按哈希），不一致 → `confirmation-identity-mismatch`，不写文件（D-004 / D-018 既有合同，D-3 不改）。C 阶段演示第 8 项正是这条保护的现场证据。
- **真正的跨进程一致性**（需 IPC / 共享受控凭据 / 启动握手设计）列入 §9 待用户单独批准事项，D-3 不设计、不实现、不声称。

### 5.3 多身份加载与受控启动器约束（本轮 P0-2 的实现前提）

某些受信场景需要在**同一个进程内**加载**两个不同**的受控身份（演示第 8 项的「错绑 subject」、评估第 5 项的 `service-B-subject`、集成测试的 `service-A` 对照）。M1 下的合法做法是：

1. 受控启动器在临时目录下预置**两个受控身份根**，各含一个 `identity.json`（如 `identity/identity.json` 与 `attacker/identity.json`）。
2. 对每个身份分别调用一次真实的 `load_runtime_identity()`，得到两个 `RuntimeIdentity`。**全程不绕过加载器、不构造伪对象。**
3. 用其中一个身份构造的 Host 去消费另一个身份创建的 confirmation → 仍应返回 `confirmation-identity-mismatch`、不写文件。

> **实现陷阱（必须写进实现说明，否则演示会误失败）**：`load_runtime_identity()` 会对传入的 `environ` 做 §1.1 的相等性断言。若受控启动器**自身进程环境**里设置了 `MCP_NOTES_SUBJECT=<主身份>`，那么加载**第二个**身份文件时断言会失败（`env != file_subject`）。因此二选一：
> - **推荐**：受控启动器自身进程**不设置** `MCP_NOTES_SUBJECT`（只在为 Server 子进程构造的 env 字典里按需设置，或干脆不设、改设 `MCP_NOTES_IDENTITY_FILE`）；
> - 或：加载第二身份时显式传入**不含该键**的映射（例如 `{}`）。`environ` 只是受信调用方提供的断言输入，**永不产生值**，传空映射只是跳过可选断言，不构成 env 绕过。

### 5.4 `RuntimeIdentity` 的「私有哨兵」定位（本轮 P1-1 收紧）

- `RuntimeIdentity` 是不可变值对象（`frozen dataclass`），携带已验证 `subject`，通过模块私有构造哨兵使**公共 API 层面**无法用任意字符串直接构造。
- **明确降级表述**：私有哨兵**不是安全边界**，也**不能证明**「只能由加载器产出」。Python 没有进程内的语言级隔离——同进程代码仍可访问私有成员、直接调用内部构造、或 monkeypatch 模块符号。它的作用**仅限于受信代码内部的类型/API 防呆**（防止调用点误传裸字符串、防止未来重构悄悄绕开校验）。
- **真正的安全边界是**：
  1. MCP 客户端 / 模型**无法在服务进程内执行代码**——它们只能通过 Tool 表面提交 `title`/`description`/关键词，形状守卫（`server.py:231`）阻断一切额外字段；
  2. MCP 客户端 / 模型**无法写入受控身份根**（部署带外预置、客户端不可写，§1.2）；
  3. MCP 客户端 / 模型**无法控制受控启动器的环境**（若能控制整个进程环境，该部署不在 D-3 信任模型内，§1.2）。
- 推论：若攻击者已能在服务进程内执行任意 Python 代码，则身份机制连同整个进程均已失守，**这不在 D-3 的威胁模型内**，任何构造哨兵都无法补救。

### 5.5 绑定不变量总结

`subject` 值只来自受控身份文件 + 每进程 bootstrap 经真实加载器注入 `RuntimeIdentity` + `correlation_id` 服务端派生 + 记录只存哈希 + Host 用自身 `RuntimeIdentity` 重建上下文 + 请求期 `confirmation-identity-mismatch` 兜底 = 客户端/模型无法伪造或覆盖任一身份要素。**该链条不依赖对象同一性，也不依赖跨进程启动期断言。**

---

## 6. 范围差异：本地单用户 / 未来多用户 / Windows 与非 Windows（不得虚称）

- **本地单用户（当前，D-3 交付形态）**：一个受控身份根、一个 `identity.json`；**进程数不限**——每个参与进程各自加载一次（M1，§5.1）。无需 OS 账户绑定、无需原生凭证 API。
- **单进程内嵌形态**（tests / evals 把 Server 逻辑与 Host 放同一进程）：M1 的特例，一次加载注入两者。
- **分离 Server/Host 进程**（C 阶段 stdio 演示的实际形态，**D-3 支持**）：两进程各自安全读取**同一个**受控身份文件。D-3 **提供**「同文件 + 确定性算法 ⇒ 同值」的部署级保证，**不提供**启动期一致性断言（§5.2）；两进程被指向不同文件或文件在两次加载间被改动时，唯一保护是请求期 `confirmation-identity-mismatch`。**不得声称已支持跨进程身份一致性断言。**
- **未来多用户（D-4 及以后）**：需 `version: 2` + `subjects` 表 + 按 subject 隔离确认记录/任务文件/审计。**D-3 不实现、不解析、不声称**；遇 `version != 1` 失败关闭。
- **Windows 与非 Windows**：身份**机制**两侧一致（同一受控身份根 + 同一 schema + 同一失败矩阵）；**安全读取的原语按平台分派**——Windows 走 `OBJ_DONT_REPARSE` HANDLE 链（已实机验证），POSIX 走 `O_NOFOLLOW`+`fstat` fd 链（**沿用 D-2 现状：算法级/mock 已验证，真实链接夹具 D2-L1…D2-L4 仍 blocked-until-approved，未实机验证**）。不依赖任何原生 OS 凭证 API。D-3 **明确不声称**已实现 Windows 令牌 / POSIX uid 绑定。
- **部署前提不可省**：受控身份根必须由可信部署预置且客户端不可写；`MCP_NOTES_IDENTITY_FILE` 必须由受控启动器设置。客户端可控整个进程环境的部署不在信任模型内（§1.2）。
- **不公开部署、不联网**：身份加载为本地文件读取，零网络 I/O。

---

## 7. 最小改动范围、测试矩阵、离线评估增量、DoD、回归命令

### 7.1 实现最小改动范围（供后续实现 + Codex 复核，本轮不写）

**新增**
- `src/mcp_notes/identity.py`（纯标准库、离线）：
  - `MAX_IDENTITY_BYTES = 4096`、`IDENTITY_SCHEMA_VERSION = 1`、`_ALLOWED_SUBJECT_KIND = "deployment-provisioned"`；
  - `RuntimeIdentity`（frozen，私有哨兵构造）；
  - `load_runtime_identity(environ, identity_file_path=None) -> RuntimeIdentity`：§1.2 路径校验 → §1.3 平台分派安全读取 → §1.4 schema 校验 → §1.1 env 相等性断言；任何失败 `raise TaskPublishError(INVALID_ARGUMENTS)`；
  - 平台分派：`sys.platform == "win32"` 时用 `safe_task_write.open_task_root` + `_nt_open`；否则用 `safe_task_write_posix._posix_supported` + `_open_root` + `O_NOFOLLOW`/`fstat`（包内内部复用）。
- `tests/test_identity.py`（见 §7.2）。

**修改（仅 2 个源文件 + 调用点 + 受控启动器夹具）**
- `server.py`：新增 `MCP_NOTES_IDENTITY_FILE` 配置；`ServerConfig` 持有 `RuntimeIdentity`（不再持有裸 `subject` 字符串作为可注入入口）；`from_env` 在 Server 进程 bootstrap 处调用一次 `load_runtime_identity()`；保留构造期 `_valid_subject` 守卫作为纵深防御；身份失败沿用 `main()` 既有稳定码退出路径（`server.py:376-378`）。
- `host.py`：`TrustedHostController.__init__` 第三参数改为 `identity: RuntimeIdentity`；非 `RuntimeIdentity` → `invalid-arguments`。**不新增 `main()`**（本轮 P1-2）。
- **调用点机械更新（零测试删除）**：`TrustedHostController(` 共 **12 处**、`ServerConfig(` 共 **2 处**，按需要的适配类型分为两类：

  | 位置 | 处数 | 适配类型 |
  |---|---|---|
  | `demo/mcp_stdio_demo.py:126` / `:137` | 2 | 主身份：受控启动器预置 `identity/identity.json` → 加载一次 → 注入 |
  | `demo/mcp_stdio_demo.py:145`（`"attacker-subject"`） | 1 | **第二受控身份根**：预置 `attacker/identity.json` → 再加载一次（§5.3）→ 注入；仍期望 `confirmation-identity-mismatch` |
  | `evals/run_c_phase_eval.py:150/165/181/194` | 4 | 主身份，同上 |
  | `evals/run_c_phase_eval.py:208`（`"service-B-subject"`） | 1 | 第二受控身份根，同 demo 第 8 项 |
  | `tests/test_mcp_integration.py:353` | 1 | 主身份夹具 |
  | `tests/test_mcp_integration.py:405/421`（`"service-A"`） | 2 | 第二受控身份根夹具 |
  | `tests/test_mcp_integration.py:439`（`"bad subject"`） | 1 | 改为断言「传非 `RuntimeIdentity` → `invalid-arguments`」；**非法 subject 字符串的覆盖迁移到「身份文件内 `subject` 非法 → 加载失败关闭」**（§7.2 C-17），断言强度不降低 |
  | `evals/run_c_phase_eval.py:70` / `tests/test_server_entry.py:81`（`ServerConfig(`） | 2 | 改为持有 `RuntimeIdentity`（由夹具身份文件加载） |

- **受控启动器夹具（demo / evals 新增少量准备代码，不是纯机械替换）**：在既有临时目录下创建 `identity/` 与第二身份根目录并写入 `identity.json`；demo 的子进程 env 由 `MCP_NOTES_SUBJECT` 改设 `MCP_NOTES_IDENTITY_FILE`；**受控启动器自身进程不设 `MCP_NOTES_SUBJECT`**（§5.3 实现陷阱）。
- 测试/演示/评估全部改为写入真实 `identity.json` 夹具后调用真实 `load_runtime_identity()`——**不提供绕过加载器的测试后门**。

**完全不改**
- `contracts.py` / `tasks.py`：`_valid_subject` / `_valid_correlation_id` / `TrustedContext` 保持 D-1 原样。
- `safe_task_write.py` / `safe_task_write_posix.py`：**零修改**，仅被只读复用（D-2 合同与 196 基线不动）。
- sqlite 状态机、no-replace 发布路径、审计事件形状：不动。
- 稳定错误码集合：不扩大（不引入 `identity-unavailable`）。

### 7.2 测试矩阵（设计）

**A. 值来源单一性（P0-1）**
1. 身份文件缺失 + **无** env → 失败关闭。
2. 身份文件缺失 + **有**合法 env → **仍失败关闭**（证明 env 不是后备）。
3. 文件合法 + env 未给出 → 加载成功。
4. 文件合法 + env 给出且相等 → 加载成功，结果与第 3 项**逐字节相同**。
5. 文件合法 + env 给出但不等 → 失败关闭。
6. **等价不变量**：对第 3/4 项环境，删除 env 后重新加载，结果不变。

**B. 安全读取（P0-2，全部离线、mock/夹具，不创建真实链接）**
7. `<name>` 含分隔符 / `..` / `\x00` / UNC / 驱动器前缀 / 不符白名单 → 失败关闭。
8. 平台能力缺失（mock 掉 `O_NOFOLLOW`/`O_DIRECTORY`/`dir_fd`/`fstat`；Windows 侧 mock `_NATIVE_AVAILABLE=False`）→ 失败关闭，且**不发生任何字符串路径读取**（以 mock 断言 `open()`/`os.stat(path)` 未被调用）。
9. 身份根链打开失败（mock D-2 原语抛 `SafeWriteError`）→ 映射为 `invalid-arguments`，不泄露原始异常。
10. 身份文件为目录 / FIFO / 设备（mock `fstat` 返回相应 `st_mode`）→ 失败关闭。
11. **检查后替换（TOCTOU）**：mock 令路径条目在打开后被替换，断言读取结果仍来自已打开 fd、且类型断言基于 `fstat(fd)` 而非路径。
12. 权限拒绝 / 读取 IO 失败 → 失败关闭，稳定码，无原始 `OSError` 泄露。
13. 文件 4096 字节边界通过；4097 字节 → 失败关闭。
14. **真实 symlink / junction 身份根与身份文件**（4 项）→ **默认 skip 占位**，blocked-until-approved，不创建、不运行（与 D2-L1…L4 同规格）。

**C. schema（P1-1）**
15. 顶层非 object → 失败关闭。
16. `version` 缺失 / 字符串 / `True`（bool）/ `2` → 失败关闭。
17. `subject` 缺失 / 非 str / 空 / 含空格或 CJK / 129 字符 → 失败关闭；128 字符合法 → 通过。
18. `subject_kind` 缺失 / 非 str / 非法值 → 失败关闭。
19. 出现未知顶层键 → 失败关闭。
20. 非 UTF-8 字节 / 带 BOM / JSON 语法错误 → 失败关闭。

**D. 注入与绑定（M1 进程模型 + 既有合同回归；v3 已消除 v2 的矩阵矛盾）**

21. `TrustedHostController` 传裸 `str` subject → `invalid-arguments`（生产构造器拒绝裸 subject）。
22. **防呆（非安全边界）**：公共 API 层面用任意字符串直接构造 `RuntimeIdentity` 会失败。
    > 断言口径（本轮 P1-1）：本项只证明**类型/API 防呆生效**，**不得**在测试名或注释中表述为「证明只能由加载器产出」或「客户端无法伪造身份对象」。同进程代码可访问私有成员，这是 Python 语言事实；真正的边界见 §5.4。
23. **单进程内嵌（M1 特例）**：一次 bootstrap 注入 Server 与 Host → approve 全链路通过。
24. **多身份（M1 常规路径，v3 重写）**：在受信测试进程内**两次独立调用真实 `load_runtime_identity()`**，分别读取**两个不同的受控身份根**（模拟两个进程各自加载），得到两个不同的 `RuntimeIdentity`；用身份 B 构造的 Host 去消费身份 A 创建的 confirmation → 仍返回 `confirmation-identity-mismatch`、不写文件。
    > **与 §5.1 的相容性说明（本轮 P0-2 的关键）**：这**不违反**「每进程一次」，因为该约束针对的是**生产 bootstrap 入口**；加载器本身无全局状态、可重入，受信代码多次调用是模拟多进程的正当手段，且每次都走完整安全读取，**不绕过加载器**。
    > 同时按 §5.3 的实现陷阱：该测试进程**不得**在自身 `os.environ` 中设置 `MCP_NOTES_SUBJECT`，或在加载第二身份时显式传不含该键的映射。
25. **分离进程（M1 常规路径，新增）**：`demo/mcp_stdio_demo.py` 保持现有形态——Server 子进程与 Host 父进程**各自**加载同一个受控身份文件，8 项断言全通过（尤其第 4 项 approve 成功发布、第 8 项错绑身份 `confirmation-identity-mismatch`）。这是 v3 P0-1 的验收现场。
26. `correlation_id` 回归：不可由客户端提供/覆盖；`TrustedContext` 仍要求 64-hex；Host 仅从 `lookup_correlation_id` 取回。

**E. 稳定码唯一输出（P1-3 前提；v3 已按本轮 P1-2 收敛到可验收入口）**

27. **`server.main()` 入口** bootstrap 身份失败（身份文件缺失 / schema 非法 / 相等性断言失败各一例）：以 subprocess 启动，断言 `stdout` 为空、`stderr` **仅**含 `invalid-arguments`、退出码非零；输出中不含绝对路径、用户名、`Traceback`、`Errno`。
28. **受控启动器入口**（Host 侧当前唯一实际启动路径）：以 subprocess 运行**与真实 demo/eval 同一套 bootstrap 的受测启动包装器**（其构造流程严格为 `identity = load_runtime_identity(MCP_NOTES_IDENTITY_FILE); TrustedHostController(..., identity=identity)`——**受测启动包装器只能经 `MCP_NOTES_IDENTITY_FILE` 注入受控身份文件路径，不得保留 `subject=` 入口**，否则会制造 D-3 §5.1 禁止的「绕开加载器直接传裸 str」路径；不为 `host.py` 加 `main()`），通过**显式覆盖 `MCP_NOTES_IDENTITY_FILE` 环境变量**指向一个**确定性破坏的身份文件**来触发加载失败，同等断言（`stdout` 空、`stderr` 仅 `invalid-arguments`、非零退出、无路径/用户名/`Traceback`）。破坏身份文件由测试夹具固定提供三类，分别对应已覆盖的失败分支：
    - (a) 缺失文件：指向不存在路径 → 触发「身份文件必须存在」失败关闭；
    - (b) 非法 schema：如 `version: 2` 或含未知顶层键的 JSON → 触发 schema 拒绝；
    - (c) 非普通文件：指向目录 → 触发类型断言失败。
    > **确定性要求（本轮非阻断完善）**：失败**不得依赖偶发环境**（误删生产文件、权限意外变化等）。测试专用受测启动包装器必须在**测试内显式设置** `MCP_NOTES_IDENTITY_FILE` 为上述夹具路径，且复用与生产中 `demo/mcp_stdio_demo.py` 完全一致的调用路径——先 `load_runtime_identity()` 取得 `RuntimeIdentity`，再 `TrustedHostController(identity=identity)`（**不保留 `subject=` 入口**，否则违反 D-3 §5.1 生产构造器拒裸 str 规则、制造绕过路径）；无论宿主环境如何，身份加载失败都被构造为可控、可复现的输入。实现前须在 `tests/test_identity.py`（或 `tests/test_mcp_integration.py`）中提供一个最小「受测启动包装器」：仅做 env 注入 + bootstrap + 稳定码退出（`sys.exit` 非零 + `stderr` 写 `invalid-arguments`），作为测试 27/28 的统一 subprocess 入口。
    > v2 的「Host 入口同等断言」已删除——`host.py` 无 `main()`（`host.py:39`），该断言在当前代码上无对象可测（本轮 P1-2）。未来新增 Host 入口时按 §3 前瞻性条款补测。

**平台**：全部纯标准库，Windows 宿主可直接跑；任何需真实 OS 账户 / 原生凭证 / 真实链接的测试标默认 skip 占位（blocked-until-approved），不创建、不运行。
**基线**：保 196 零删除（164 D-1 + 32 D-2 全保留），新增为增量；调用点为机械改造 + 受控启动器夹具准备，不弱化任何既有断言（`"bad subject"` 用例的强度按 §7.1 表迁移到 C-17，不删除覆盖）。

### 7.3 离线评估增量

D-3 不扩张 40 例评估套件（属 D-6）。离线贡献为 `tests/test_identity.py` 回归 + 保持 C 阶段 11/11 评估、8/8 演示全绿。**评估基线计数不因 D-3 变化**（评估/演示脚本仅做「受控身份根夹具准备 + `RuntimeIdentity` 注入」的适配，断言与用例数不变）。**演示保持现有分离进程形态**（Server 子进程 + Host 父进程各自加载同一身份文件），这是 v3 相对 v2 的关键差异：v2 的单进程唯一模式会迫使演示改架构或放弃 8/8，v3 不需要。

### 7.4 DoD（完成定义）

1. **值来源唯一**：最终 `subject` 只能由受控身份根下的 `identity.json` 产出；`MCP_NOTES_SUBJECT` 对结果贡献恒为零（等价不变量测试通过）。
2. **安全读取可实施且已验证**：身份根与身份文件全程经 fd/HANDLE 链打开，拒绝 reparse/symlink/非普通文件，类型断言基于已打开 fd；无任何字符串路径读取回退；能力缺失失败关闭。
3. **失败关闭无泄露**：§3 全部情形均返回 `invalid-arguments`，不回退默认主体，不泄露路径/正文/用户名/环境值/原始异常。
4. **稳定码唯一输出（范围已按本轮 P1-2 收敛）**：**当前存在的两类入口**——`server.main()` 与受控启动器（demo / evals / 测试夹具）——身份失败时 `stdout` 空、`stderr` 仅稳定码、非零退出（测试 27/28 证明）。这是不新增 `identity-unavailable` 的前提。**不再包含**「Host 所有启动入口」这一无对象可测的全称承诺；`host.py` 本轮不新增 `main()`。
5. **生产构造器不接受裸 subject**：`TrustedHostController` / `ServerConfig` 仅接受 `RuntimeIdentity`；`RuntimeIdentity` 由 `load_runtime_identity()` 产出，构造哨兵为**受信代码内的类型/API 防呆，不作为安全边界主张**（§5.4）。
6. **`subject` 无法从 Tool 参数 / 模型文本 / MCP 消息到达**（形状守卫 + 静态断言证明）。
7. **`correlation_id` 不变**：服务端派生、64-hex、不可覆盖——回归证明无退化。
8. **不声称未做到的事**：跨进程启动期一致性断言标注为不支持；对象同一性不作为一致性论据；私有哨兵不作为安全边界；多用户 / OS 凭证 / PKI 标注为 blocked-until-approved。
9. **基线保留**：`unittest` ≥ 196（188 通过 + 8 skip，零删除）、评估 11/11、**演示 8/8（分离进程形态保持不变，测试 25）**、`pip check` 干净、`git diff --check` 通过。
10. **D-2 文件零修改**：`safe_task_write.py` / `safe_task_write_posix.py` diff 为空。
11. **进程模型自洽**：M1 为唯一模型；文档、测试矩阵、demo/evals 实际形态三者一致，不存在「要求同一实例」与「构造不同身份」并存的矛盾（本轮 P0-1 / P0-2）。
12. 无新增依赖、无网络、无敏感信息记录。

### 7.5 回归命令（与 D-2 一致；D-3 仅新增 `tests/test_identity.py`）

```bash
# Git Bash / Linux shell
cd projects/03-mcp-tool-server
PY=.venv/Scripts/python.exe
$PY -m compileall -q src tests
$PY -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -4
$PY -m unittest tests.test_create_task tests.test_mcp_integration tests.test_server_entry tests.test_identity 2>&1 | tail -3
$PY evals/run_c_phase_eval.py 2>&1 | tail -4
$PY demo/mcp_stdio_demo.py 2>&1 | tail -4   # 必须仍是分离进程形态且 8/8（DoD 9 / 测试 25）
$PY -m pip check
git diff --check && git diff --cached --check
git diff --stat -- src/mcp_notes/safe_task_write.py src/mcp_notes/safe_task_write_posix.py   # 必须为空（DoD 10）
grep -n "StdioServerParameters" demo/mcp_stdio_demo.py   # 必须仍存在：演示未被改成单进程（DoD 11）
```

---

## 8. 不破坏现有 D-1/D-2 合同与基线

- **D-1 合同**：`_valid_subject` / `_valid_correlation_id` / `TrustedContext` 强制校验全部保留；D-3 仅改变「subject 从哪加载、以何种类型注入」，不改变「subject 必须满足白名单、correlation_id 必须 64-hex」。
- **D-2 合同**：`safe_task_write.py` / `safe_task_write_posix.py` **零修改**，仅被只读复用；no-replace 发布、稳定错误语义、`task_root` 句柄验证完全不动；196 基线（188+8 skip）全保留。D-2 原语抛出的稳定码在 identity 边界内映射为 `invalid-arguments`，**不改变发布路径对外语义**。
- **sqlite 状态机**：确认状态机、审计（不存正文）、幂等映射不变；`confirmation-identity-mismatch` 语义不变。
- **C 阶段演示架构不变（v3 新增保障）**：`demo/mcp_stdio_demo.py` 保持 **spawn 独立 Server 子进程 + 父进程 Host** 的分离形态（`StdioServerParameters` 仍在），仅新增受控身份根夹具与 `RuntimeIdentity` 注入；8 项断言与其语义一字不改。v2 的单进程唯一模式会破坏这一点，v3 已修正（本轮 P0-1）。
- **失败关闭语义**：复用 `invalid-arguments`，稳定码集合不扩大。
- **网络口径**：保持「仅本地 stdio、测试期阻断外部网络」；身份加载为本地文件读取，不新增任何网络连接。

---

## 9. 仍需用户单独批准的事项（blocked-until-approved）

1. **OS 原生凭证绑定**（Windows 令牌/SID、POSIX uid）作为 subject 的附加/替代来源：需原生 API、真实 OS 账户、平台分裂代码。
2. **签名身份清单 / 密钥材料 / PKI**：需密钥管理，与「仓库不放密钥」冲突。
3. **真实多用户环境**（多 OS 账户 / 多 subject 隔离测试）：需 D-4 + 真实多用户测试环境。
4. **跨进程 Server/Host 身份一致性断言**（IPC / 共享受控凭据 / 启动握手）：D-3 明确不支持（§5.2），真正实现需单独设计与批准。**注意**：D-3 支持的是「分离进程各自加载同一文件」这一部署形态（§5.1 M1），**不是**跨进程一致性断言机制，两者不可混淆。
5. **真实 symlink / junction 身份根夹具**（测试 14 的 4 项占位）：与 D2-L1…D2-L4 同规格，未批准不创建、不运行。
6. **为 `host.py` 新增 CLI / 服务启动入口**：本轮明确不做（§3 前瞻性条款）；若未来需要，须连同稳定码输出断言一并设计。
7. **把身份文件移至共享 / 网络位置的部署变更**：会引入网络与可用性假设，必须保持本地。
8. **WSL / Linux 本机 / 远程 runner 上的真实 POSIX 验证**：沿用 D-2 的 blocked-until-approved 口径。
9. **公开部署 / 网络传输**：明确超出 D-3（D-3 零网络）。

D-3 可做的部分：**受控身份根 + 部署预置 `identity.json` + fd/HANDLE 链安全读取 + 每进程一次 bootstrap 注入（M1，含现有分离进程演示）**（纯本地、离线、Windows 宿主可跑）。

---

## 10. 文档姿态与敏感信息约束（强制）

- 本设计原为 design-only（规划中 / 设计完成，尚未实现）；**D-3 实现已由本地提交 `d14341d` 落地（未 push、未建 PR；本次 Codex 复核中）**，可表述为「已实现」（受控身份根 + 部署预置 identity.json + fd/HANDLE 链安全读取 + M1 每进程一次注入）。
- **不公开部署，不允许公网监听**；不新增网络连接（身份加载仅本地文件读取）。
- **不把模型输出、MCP 客户端文本、环境变量中的未受控输入当作可信身份**——`MCP_NOTES_SUBJECT` 仅为可选相等性断言，**永不产生值**。
- **不记录**：用户名、绝对路径、密钥、Cookie、鉴权头、环境变量值、原始异常或堆栈；审计/日志仅存稳定事件类型与稳定错误码、`task_id`/`confirmation_id` 安全标识。
- 任何失败对外仅暴露稳定错误码，绝不回显路径/正文/异常。
- 部署前提必须与代码同时成立：受控身份根客户端不可写；`MCP_NOTES_IDENTITY_FILE` 只来自受控启动器；否则该部署不在 D-3 信任模型内。
- **不得把语言级私有约定说成安全边界**：`RuntimeIdentity` 的私有构造哨兵是受信代码内的防呆，不是隔离机制（§5.4）。
- **不得把「分离进程各自加载同一文件」说成「跨进程身份一致性断言」**（§5.1 / §5.2 / §9-4）。

---

## 11. 复核修订记录

- **v1（2026-08-08）**：初版设计包，DECISIONS **D-025**（已 superseded）。Codex 复核结论：**需修改，3 个 P0**（env 仍为第二权威来源；安全读取无可实施算法；分离进程启动期一致性断言无法实现）+ 3 个 P1。
- **v2（2026-08-08）**：按 v1 结论修订，DECISIONS **D-026**（已 superseded）。Codex 复核结论：**需修改，2 个 P0 + 3 个 P1**——① 单进程 + 同一实例模型与现有 stdio 演示（`demo/mcp_stdio_demo.py:85` spawn 子进程、`:126` 父进程建 Host）冲突，却承诺演示 8/8；② 测试矩阵自相矛盾（要求同一实例又要求构造不同 `RuntimeIdentity`）；③ 私有哨兵被当作安全边界；④「Host 所有启动入口只输出稳定码」不可验收（`host.py:39` 是库类、无 `main()`）；⑤ `ARCHITECTURE.md:81` / `PRD.md:128` 仍引用已 superseded 的 D-025。**v2 的 §1 身份来源部分（env 退化、schema、fd/HANDLE 链读取、错误映射）经 Codex 判定已闭环，v3 原样保留。**
- **v3（2026-08-08，本文件）**：按 v2 结论修订，见文首 v3 修订说明表；对应 DECISIONS **D-027**。核心变更：进程模型由「单进程 + 同一对象实例」改为 **M1 每进程一次加载（支持现有分离进程演示）**；测试 24 改为「两次真实加载、两个受控身份根」；私有哨兵降级为防呆；稳定码 DoD 收敛到 `server.main()` 与受控启动器两类可测入口；旧 D-025 引用全部更新。**原为设计包，未实现、未暂存、未提交**（v3 当时历史状态记录）；**后已由本地提交 `d14341d` 落地（未 push、未建 PR；本次 Codex 复核中）**——此条为 v3 当时的历史状态，实际代码已实现并随 `d14341d` 提交。
- 实现阶段若再有 P0/P1，将在本节续记修复内容与验证结果；范围严格限定 D-3 相关文件，不进 D-4/D-5/D-6、不装依赖、不创/跑真实 symlink/junction、不改 P2/C 安全核心与 sqlite 状态机、不碰 `.workbuddy/`、不 push/不建 PR。
