# 干净源码检出复现记录

2026-09-22。助手在提交 `b7476219cf9bd427dc3537154485223a3ef4a911` 的独立 detached Git 工作树复核；检出后 `git status --porcelain=v1 -uall` 为 0。这里的“干净”指**源码与应用状态隔离**，不指新电脑重新安装依赖。

## 环境边界

独立工作树保留提交中的 P1、P2、P3 和工作台源码。三个项目的 `.venv` 通过被 Git 忽略的 Windows 目录联接复用本机原有虚拟环境；没有安装、升级或下载依赖。应用测试只在临时目录与新建 `.runtime` 状态运行，不访问原项目数据库、容器、在线服务或 P2 真实账本。`integrations/graduation/common.py` 为工作进程设置当前检出项目的 `src` 为 `PYTHONPATH`，因此复用的是解释器与包，业务源码来自本次检出。

`check_environment.py` 检查通过：P1 为 Python 3.14.3 / pydantic 2.13.4；P2 为 Python 3.14.3 / pydantic 2.13.4 / langgraph 1.2.9 / langgraph-checkpoint-sqlite 3.1.0；P3 为 Python 3.13.14 / mcp 2.0.0 / pydantic 2.13.4。该探针只核对选定包，不证明全新机器可安装。

## 实际命令与结果

从独立检出根目录运行：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/check_environment.py
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate.py --output apps/course-platform/.runtime/repro-tests.json
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate_library.py --output apps/course-platform/.runtime/repro-library.json
```

- 应用完整离线回归：**55/55 通过，0失败、0错误、0跳过，170.923秒**；包括三角色 HTTP 权限、真实离线 P1/P2/P3 工作流与旧测试。结构化结果复制至 [clean-source-tests.json](results/clean-source-tests.json)。
- 固定合成检索：8篇资料、20题；有依据题词法 Hit@1 18/18，无依据正确返回空2/2；精确子串基线8/18。结果见 [clean-source-library.json](results/clean-source-library.json)。这不代表真实资料检索或报告内容质量。
- Python 24个应用/测试文件语法检查与三个前端 JS 文件 `node --check` 通过。
- 新建私有应用状态、启动本机 `127.0.0.1:8893` 后，`GET /`、`GET /api/bootstrap`、`GET /api/auth/session` 均返回200；服务按核验过的进程标识停止。见 [clean-source-smoke.json](results/clean-source-smoke.json)。首次 PowerShell HTTP 探针未完成，另一次脚本使用保留变量名失败；改用 `curl.exe --noproxy '*'` 的最终检查通过。未把探针问题归因为应用缺陷。

原 G3 三角色浏览器操作记录仍见 [G3验收](graduation/G3-ACCEPTANCE.md)。本次独立检出重跑的是三角色 HTTP 行为测试与默认模式 HTTP 启动；**未在该检出重做三角色浏览器操作或操作系统下载落盘检查**。

## 发布审查与未完成项

发布提交只包含根导航/启动入口和 `apps/course-platform` 共94个文件。16张截图原内容均为JPEG，已仅把扩展名从 `.png` 更正为 `.jpg` 并更新引用，图片 SHA-256 未变。暂存内容逐项检查：无 `.runtime`、`.venv`、真实 `.env`、数据库、非普通文件或扫描命中的密钥/个人路径；64份 Markdown 的相对链接存在。原开发工作树的668条既有状态路径未改。未 push，也未改 `main`。

仍需全新机器从锁文件安装与启动验证、操作系统下载落盘复核、正式资料授权、独立内容评分、教师当届要求对照和学习者本人讲解。P2历史真实内容验收未通过；永久预算417/500分、109/109次调用已封顶。本次真实模型调用0次，新依赖0个。

## 最新提交的独立源码复演（2026-09-23）

以上 `b747621` 记录保留为历史结果。本次从 `codex/course-platform-ui` 的提交 `5636d6d49665f78e403157be5f38472bd55b171f` 新建另一个 detached 工作树 `H:\暑假学习\编程学习\ai-application-portfolio-course-platform-repro-g4-20260923`，开始和结束时 `git status --porcelain=v1 -uall` 均为空。旧 `b747621` 复现工作树未切换。三个项目的忽略目录 `.venv` 仍通过 Windows Junction 复用原开发环境中的解释器和已安装包；**没有**在新机器重装依赖。应用和 P1/P2/P3 业务源码来自这次独立检出；未访问原项目运行状态、数据库、容器、云资源或 P2 真实账本。

从新检出根目录执行：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/check_environment.py
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate_library.py --output apps/course-platform/.runtime/repro-g4-library.json
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate.py --output apps/course-platform/.runtime/repro-g4-tests.json
```

- [环境探针](results/repro-g4-environment.json)：`ready: true`；P1/P2 Python 3.14.3、P3 Python 3.13.14，列出的关键包与既有环境一致。探针不验证全部锁定依赖或新机器安装。
- [固定合成检索](results/repro-g4-library.json)：8篇、20题；有依据题 Hit@1 18/18，无依据题正确返回空2/2；精确子串基线8/18。这不是正式语料效果。
- [完整应用回归](results/repro-g4-tests.json)：**63/63通过，0失败/0错误/0跳过，185.602秒**；包括本机 HTTP 权限、实际离线 P1/P2/P3 执行和 G4 表单/ZIP 行为。真实模型调用0、新依赖0，报告内容质量仍 `not_accepted`。

本次没有在该检出复演三角色浏览器 UI 或核对操作系统下载目录；HTTP 下载可存盘的自动测试证据另见 [HTTP交付记录](graduation/HTTP-DOWNLOAD-PERSISTENCE.md)。未取得教师当届条款、正式资料授权、真人独立评分或学生独立讲解。原开发工作树 `codex/graduation-integration` 仍在 `dcb164e`，668条既有状态路径未触碰；新课设分支未 push 或合并 `main`。
