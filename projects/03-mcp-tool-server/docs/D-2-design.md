# D-2 详细设计：跨平台原子发布一致性（修订版 v5）

> 状态：**设计文档（未提交、未实现代码）**。本文件仅记录 D-2 详细设计与授权准备，供审查；不创建 `safe_task_write_posix.py`、不写任何测试、不修改 `safe_task_write.py` 运行时代码、不触碰 `.workbuddy/`。
> 硬约束：不进入 D-3、不 push、不建 PR、不新增依赖、不改 P2、不创建/运行真实 symlink 或 junction、不修改现有 164 测试基线、不触碰 `.workbuddy/`、不改其他文档或现有测试。
> 相对 v4 的修订：① §1 POSIX 路径拆分改为**单一规则**（根标记=单个开头 `/`，移除该 `/` 后按单 `/` 分割；拒绝 `//var/tasks`、`/var//tasks`、`/var/tasks/` 尾斜杠、`/var/./tasks`、`/var/../tasks`、相对路径、`task_root="/"` 根本身）；② §4 新增**跨平台共同部署前提**（可信部署管理、非服务主体无写/改名/删权限、服务是唯一写入者、inode 复核仅纵深防御），并收紧失败清理合同（无唯一写入者前提则**禁止按名 unlink**、返回 `task-write-failed` 失败关闭、不承诺零残留/可重试）；③ §5 D2-L2 删除命令 `rm -rf` → `rmdir`，明确 `sub` 为测试刚创建的空目录。

---

## 0. 统一门面与范围确认

- 现有 `safe_task_write.py:404` 已有 `publish_task_file()`；`tasks.py:44` 导入、`tasks.py:666` 调用；`host.py` 不直接写文件。D-2 在 `safe_task_write.py`（平台门面）及其 POSIX 辅助模块内收敛，调用方不改签名与 `SafeWriteError` 合同。
- D-2 只承诺"POSIX 发布核心可导入/可验证"。现有 `safe_open.py` 仍 Windows-only（全量 `search_notes` Server 的 POSIX 读取支持**不属于 D-2** 范围）。

---

## 1. POSIX 受控根 fd 锚定（P0：唯一、可实现方案）

对外签名保持 `publish_task_file(task_root: str, task_id, payload)` 不变。

**删除 v2 中两种不足方案：**
- 删除 `openat(AT_FDCWD, task_root, O_DIRECTORY | O_NOFOLLOW)` 预打开**完整字符串路径**——它仍对 `task_root` 整体做单步打开，祖先 symlink 可在到达前被跟随。
- 删除"受信 cwd"——cwd 同样不可作为可信锚点。

**固定采用此方案：**
- POSIX 每次发布从 `/` 的目录 fd 开始：`root_anchor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)`。
- **`task_root` 绝对路径拆分规则（精确、单一）：**
  - POSIX 根标记是**单个开头 `/`**。
  - 必须 `os.path.isabs(task_root)`；相对路径 → `SafeWriteError(TASK_ROOT_UNSAFE)`。
  - 仅移除**这一个开头 `/`**，再按**单个 `/`** 分割为组件列表。
  - 对每一段 `comp`：
    - 空段（来自 `//var/tasks`、`/var//tasks`、`/var/tasks/` 尾斜杠）→ 拒绝；
    - `.`（`/var/./tasks`）→ 拒绝；
    - `..`（`/var/../tasks`，任何位置上溯）→ 拒绝；
  - 分割后**必须至少有一个合法组件**；因此 `task_root="/"`（移除开头 `/` 后为空）也 → `task-root-unsafe`。
  - 合法示例：`/var/tasks` → 移除开头 `/` 得 `var/tasks` → 按单 `/` 分割 `["var", "tasks"]`，全非空、无 `.`/`..` → 合法。
  - 非法示例：`//var/tasks`（开头双斜杠/空段）、`/var//tasks`（空段）、`/var/tasks/`（尾斜杠空段）、`/var/./tasks`（`.` 段）、`/var/../tasks`（`..` 段）、`var/tasks`（相对路径）、`/`（空组件）→ 全部拒绝。
- 对每个组件 `comp` 只允许相对已验证父 fd 的 `openat`：`h = os.open(comp, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)`；随即 `st = os.fstat(h)` 断言 `stat.S_ISDIR(st.st_mode)` 必须为真。
- **所有目录 fd（`root_anchor` 与每一级 `h`）持有到最终创建、冲突读取、失败清理、目录 `fsync` 全部完成，才逆序关闭。**
- **严禁**：验证通过后关闭父 fd、再按组件名重新打开（这会引入 TOCTOU 窗口并丢失锚点链）。
- 禁止 `realpath` 作安全判断（会主动解析 symlink）；除从 `/` 起的一次性 walk 外禁止字符串路径回退。
- 能力缺失（`dir_fd` 不支持 / 无 `O_NOFOLLOW` / 无 `O_DIRECTORY` / 无目录 `fsync`）→ 稳定 `task-root-unsafe`，**绝不降级字符串路径**。

**最终文件创建：** `os.open(fname, O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW, 0o600, dir_fd=parent_fd)`。`O_EXCL` 保证不覆盖；`O_NOFOLLOW` 防御最终组件已是 symlink（open 失败，而非跟随写/读目标）。

---

## 2. 平台模块导入与门面（P0：可行性）

**现状问题：** `safe_task_write.py:28` 与 `safe_open.py:38` 均在模块顶层无条件 `import msvcrt`；POSIX 上导入会在平台分发前失败，导致整个模块不可导入，违反"POSIX 发布核心可导入"的承诺。

**D-2 方案：**
- `safe_task_write.py` 改为**无 Windows-only import 的平台门面**：保留 `publish_task_file()`、`SafeWriteError`、四个 `TASK_*` 稳定码；不在模块顶层 `import msvcrt`，仅在函数内按需延迟导入 Windows 专属实现。
- Windows 原生实现移入**仅 Windows 导入**的模块（如 `safe_task_write_win.py`，内部 `import msvcrt`）；POSIX 实现位于 `safe_task_write_posix.py`（仅用标准库 `os`/`stat`）。
- **Windows 下保留现有内部测试所需的兼容导出**（原模块级符号如 `TASK_*` 常量、异常类、必要 helper），避免现有 **164** 基线导入断裂。
- `tasks.py` 与 `host.py` 调用签名不变（仍 `from mcp_notes.safe_task_write import publish_task_file, SafeWriteError`）。
- **不虚称完整 MCP Server 跨平台**：D-2 仅使 POSIX 发布核心可导入/可验证；`safe_open.py` 的 `search_notes` 读取 POSIX 支持明确不在 D-2。

---

## 3. 冲突目标安全分类（P0：EEXIST 合同补全）

不应写"最终 symlink 一定返回 ELOOP"。`O_CREAT | O_EXCL` 遇既有对象通常返回 **`EEXIST`**（symlink 偶然返回 `ELOOP` 仅是其中一种情形，不能作为唯一假设）。

**`EEXIST` 后安全分类精确顺序（POSIX）：**
1. 始终使用仍持有的已验证 `parent_fd`；**不使用** `os.path.exists`、`realpath`、字符串路径重开、按模糊"阶段"任选错误码。
2. 预筛：`st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)`（lstat 语义，不跟随）。
   - symlink（`S_ISLNK`）、目录（`S_ISDIR`）、FIFO（`S_ISFIFO`）、字符/块设备（`S_ISCHR`/`S_ISBLK`）、套接字（`S_ISSOCK`）、或任何非常规文件 → 统一 **`task-root-unsafe`**，不读、不写、不跟随。
   - 仅当 `S_ISREG(st.st_mode)` 为真，才进入内容读取。
3. 内容读取：相对 `parent_fd` 以不跟随方式打开：`fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)`。
   - 若该次 `open` 返回 **`ELOOP`**（竞争下变成 symlink）→ 固定 **`task-root-unsafe`**。
   - `fst = os.fstat(fd)`；若 `not S_ISREG(fst.st_mode)`（打开前后类型不一致）→ 固定 **`task-root-unsafe`**。
4. 读取字节并比对：
   - 权限、I/O、读取、解码（JSON）失败 → 固定 **`task-write-failed`**。
   - 内容相同 → `unchanged`；内容不同 → `task-conflict`。
5. 并发删除导致消失、或任何无法安全归类的情形 → 固定 **`task-root-unsafe`**（不得退回字符串路径重试）。

> 注：第 2 步 `lstat` 预筛到第 3 步 `O_NOFOLLOW` 打开之间存在**最终名称替换窗口**；该名称级 TOCTOU 无法仅靠 inode/类型复核消除，必须依赖 §4 的"跨平台共同部署前提"（可信部署 + 非服务主体无写/改名/删权限 + 服务是唯一写入者）兜底，类型/lstat 复核只是纵深防御。

**Windows 同步收紧：** `safe_task_write.py:242` `_read_existing_json()` 当前对 reparse/非常规文件读取失败返回 `None`、`safe_task_write.py:433` 映射 `task-conflict` → D-2 改为 **`task-root-unsafe`**。设计**不假定已有"reparse → task-conflict"测试**；D-2 实现须**新增一条直接覆盖该 Windows 映射的回归测试，或准确修改真实存在的用例**（实现前先 `grep` 确认现有用例断言，再决定新增/修改）。

---

## 4. fsync、close、清理路径（P0：全失败合同 + 失败清理身份保护）

### 跨平台共同部署前提（EEXIST 分支与失败清理分支共用的安全基础）
- `task_root` 及其祖先目录由**可信部署**管理。
- **非服务主体**不得拥有该目录树的写入、重命名、删除权限。
- 服务是任务根的**唯一写入者**。
- `st_dev/st_ino` 复核**仅防御意外/并发变化，不替代目录权限隔离**。
- 此前提同时覆盖 §3 `EEXIST` 分支中"lstat 预筛后再 `O_NOFOLLOW` 打开"的**最终名称替换风险**（名称级 TOCTOU 无法仅靠 inode 复核消除，必须靠部署权限隔离兜底）。

以下任一失败都必须进入同一失败处理：写入失败 / 文件 `fsync` 失败 / 文件 `close` 失败 / 父目录 `fsync` 失败。

**创建后保存身份：** `O_CREAT|O_EXCL` 成功后，立即 `cfd_st = os.fstat(created_fd)`，保存 `created_dev, created_ino = cfd_st.st_dev, cfd_st.st_ino`，供失败清理复核。

**失败后清理（身份保护，受部署前提约束）：**
- 关闭仍由本函数拥有的 fd（`close()` 报错不得重复 close：用 `try/except OSError` 包裹且每个 fd 只 `close` 一次）。
- **若部署无法保证上述"唯一写入者"前提**：失败清理**不得**按名称 `unlink`（缺乏权限隔离时名称级 TOCTOU 可能指向被替换对象，inode 复核不足以保证安全）→ 返回 **`task-write-failed`**；确认保持 `PENDING`；失败关闭；**不承诺零残留、可重试或自动恢复**。
- **若部署前提满足**：清理前以相对已验证 `parent_fd`、`follow_symlinks=False` 复核目标仍为同一 inode：
  `st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)`；比较 `(st.st_dev, st.st_ino) == (created_dev, created_ino)`。
  - 目标**缺失**（`FileNotFoundError`）/ 被**替换**（dev-ino 不匹配）/ 变成 **symlink/目录/设备**（非常规）/ 无法复核 → **不删除**，返回 **`task-write-failed`**；PENDING；不承诺零残留、不承诺可重试。
  - 仅当身份**完全相同** → 才 `os.unlink(name, dir_fd=parent_fd)`（使用已验证父 fd，绝不字符串路径），随后 `os.fsync(parent_dir_fd)`。
- **清理及其目录 `fsync` 全成功：** `task-write-failed`、PENDING、可说明无残留且可重试。
- **清理或清理后 `fsync` 任一失败：** `task-write-failed`、PENDING、失败关闭；**不保证零残留，不承诺自动重试成功**。
- POSIX 表述统一为"抛 `OSError` / `SafeWriteError`"，**不混用 Windows 的"非 SUCCESS"** 措辞。
- 保留区分：**每个 fd 最多 `close` 一次；清理成功与清理失败的语义合同不同**。
- **不声称 inode 复核本身消除了所有最终名称 TOCTOU**——它只是部署权限隔离之外的纵深防御。

---

## 5. 真实链接测试授权清单（P1：本轮绝不执行）

**门控：** `P3_ALLOW_POSIX_PUBLISH_LINK_FIXTURES=1`，**不复用** B1 的 `P3_ALLOW_FS_LINK_FIXTURES`（`tests/test_safe_index_links.py:21` 是 B1 读取测试门控，开启仍 `NotImplementedError`）。

**范围拆清：**
- **D2-L1…D2-L4：仅真实 Linux/WSL POSIX 测试。**
- Windows junction/reparse 若未来需要，另命名 **D2-W1…**，另行授权；**不得**把 Windows `mklink` 混进"仅 Linux/WSL 执行"的 D2-L 系列。

所有链接命令使用**同一 `TemporaryDirectory` 下生成的绝对、受控路径并加引号**；链接目标只可在该临时目录内、且位于 `task_root` 外，为虚构 sentinel，**绝不指向用户或系统路径**。

| # | 场景 | 命令（受控绝对路径，加引号） |
|---|---|---|
| D2-L1 | 最终文件 symlink 逃逸 | Linux：`ln -s -- "$outside/sentinel.json" "$task_root/$task_name"` |
| D2-L2 | 祖先目录 symlink 逃逸 | Linux：先 `mkdir -p "$base/task_root" && mkdir -p "$base/task_root/sub"` 建立真实目录（**`sub` 必须是该测试刚创建的空目录**），再 `rmdir "$base/task_root/sub" && ln -s -- "$base/sentinel_dir" "$base/task_root/sub"`；发布器收到 `task_root="$base/task_root/sub"`。否则若 `sub` 不被创建为目录组件，发布器不会遍历到该 symlink。 |
| D2-L3 | 检查后祖先替换 TOCTOU | 仅 POSIX 内部 syscall-adapter / 私有 test seam 注入确定性同步点（见下），**禁止 sleep** |
| D2-L4 | 已存在目标冲突不覆盖 | 预建常规 `$task_root/$task_name` 占位（独占创建 `O_CREAT\|O_EXCL`） |

Windows 未来示例（仅 D2-W，非 D2-L；当前不执行、未授权）：
- 文件链接：`cmd /d /s /c mklink "C:\...\task_root\task-x.json" "..\sentinel.json"`
- junction：`cmd /d /s /c mklink /J "C:\...\task_root\sub" "C:\...\sentinel_dir"`

**回滚修正（删除 `find <root> -type l -delete` 兜底）：** 先关闭所有 fd；再删除已知链接/junction 本身（**不跟随目标**）；最后仅清理已验证的 `TemporaryDirectory`。

**D2-L4：** 预建冲突文件须使用受控临时路径与独占创建，并断言发布前后**原始字节完全一致**。

**D2-L3 确定性钩子（移出公开 API）：** D-2 **不得**把 `pre_final_open_hook` 加进公开 `publish_task_file(task_root, task_id, payload)` 签名；公开三参数签名与 `SafeWriteError` 合同保持不变。改为在 POSIX 实现内部提供私有测试 seam（如模块级可替换的 syscall-adapter / `_open_impl`），测试通过 monkeypatch 注入确定性同步点：在父 fd 链验证完成、最终 `open` 之前原子替换祖先为 symlink。预期修正：
- 父 fd 链保持打开时，祖先路径被替换后，安全实现可能继续在"原 fd 指向的旧目录 inode"创建文件；**这不等于逃逸，不应强制要求总是 `task-root-unsafe`**。
- 断言：sentinel 从未被读/写、不会跟随新 symlink、结果落在旧目录 inode。
- 若实现额外做名称—inode 复核并检测到替换，可返回 `task-root-unsafe`；但**不能把该结果写成唯一必然结果**。

---

## 6. 计数、命令、文档同步

**保留：**
- 当前基线 **164** = 160 passed + **4** skipped。
- 新增 4 个默认 skip 后，**默认 skip = 8**。
- **"保留既有 164，不删除、不弱化"**（非总数永远固定 164）。
- C 阶段 eval 11/11 仅回归；40 例评估归 **D-6**。

**文档同步（改为实现提交同步，不延后）：**
- D-2 实现提交必须同步更新 `PRD.md`、`DECISIONS.md`、`STATUS.md` 的基线计数（将仍写 149/20/2 处更正为 164 / skip 8 / integration 23 / server_entry 6 / create_task 61 / eval 11/11）。
- 不得延后，避免文档与测试结果长期不一致。

**验证命令（按 shell 分开标注，勿混用）：**

Windows 基线（**Git Bash** 可执行；亦给出 PowerShell 等价）：
```bash
# Git Bash / Linux shell
cd projects/03-mcp-tool-server
PY=.venv/Scripts/python.exe
$PY -m compileall -q src tests
$PY -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -4
$PY -m unittest tests.test_create_task tests.test_mcp_integration tests.test_server_entry 2>&1 | tail -3
$PY evals/run_c_phase_eval.py 2>&1 | tail -4
$PY demo/mcp_stdio_demo.py 2>&1 | tail -4
$PY -m pip check
git diff --check && git diff --cached --check
```
```powershell
# Windows PowerShell 等价（非 Git Bash 语法）
cd projects/03-mcp-tool-server
$PY = ".venv/Scripts/python.exe"
& $PY -m compileall -q src tests
& $PY -m unittest discover -s tests -p "test_*.py" | Select-Object -Last 4
& $PY -m unittest tests.test_create_task tests.test_mcp_integration tests.test_server_entry | Select-Object -Last 3
& $PY evals/run_c_phase_eval.py | Select-Object -Last 4
& $PY demo/mcp_stdio_demo.py | Select-Object -Last 4
& $PY -m pip check
git diff --check; git diff --cached --check
```

Linux/WSL 真实 POSIX 验证（**Git Bash / Linux shell**，`.venv/bin/python` 或显式解释器）：
```bash
cd projects/03-mcp-tool-server
PY=.venv/bin/python   # 或 /usr/bin/python3
$PY -m compileall -q src tests
$PY -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -4
P3_ALLOW_POSIX_PUBLISH_LINK_FIXTURES=1 $PY -m unittest tests.test_d2_posix_publish -v 2>&1 | tail -20
```
注意：**不要把 Windows 路径（`.venv/Scripts/python.exe`）或 Git Bash 语法当成 Linux/WSL 通用命令；也不要把 Bash 写成 PowerShell 通用命令。** 两平台的解释器路径与管道语法（`tail` vs `Select-Object -Last`）不同。

---

## 7. 需用户单独批准事项（blocked-until-approved）

1. 创建/运行任何真实 symlink 或 junction 测试（D2-L1…L4 及未来 D2-W1…）。
2. 使用 WSL、Linux 本机、远程 Linux runner 做真实 POSIX 验证。
3. Windows `mklink`、Developer Mode、管理员权限相关操作。
4. 任何公网 CI 或远程执行环境。

D-2 明确标注：**Windows 模拟测试（unittest.mock 的 syscall-adapter，标注"算法级模拟，非真实链接验证"）可做；真实 POSIX 链接 / TOCTOU 验证 blocked-until-approved**。`PRD.md:147`、`ARCHITECTURE.md:149` 仅概念级，本设计补充后方可进入 D-2 编码。
