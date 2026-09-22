# 新机器复现核对清单

本文件是未来验收步骤，**尚未在全新机器执行**。现有证据只覆盖[干净源码检出、复用原有虚拟环境](REPRODUCIBILITY.md)。不得把清单当作完成记录。

1. 从包含 `apps/course-platform` 的 Git 提交取得源码；当前仅有本地 `codex/course-platform-ui` 提交，未 push，远程克隆是否包含此应用尚未验证。不要复制 `.runtime`、数据库、真实 `.env`、缓存或原项目账本。
2. 在 Windows 核对 P1、P2、P3 README、`pyproject.toml` 和依赖文件。已验证解释器为 P1/P2 Python 3.14.3、P3 Python 3.13.14；新机器兼容性未知。P1/P2 使用各自 `requirements.txt`，P3 使用 `requirements.lock.txt`。先看[本机只读依赖盘点](DEPENDENCY-READINESS.md)：153条记录中P1有9个现有环境缺包、19条许可证元数据待复核；P1 `requirements-api.txt` 仅适用指定 Linux 目标。安装前逐包核准精确版本、许可证、用途、离线替代方案、下载来源和费用；本轮未安装。
3. 在新的空状态目录，从仓库根目录执行（须先准备项目本地虚拟环境）：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/check_environment.py
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate.py --output apps/course-platform/.runtime/new-machine-tests.json
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate_library.py --output apps/course-platform/.runtime/new-machine-library.json
```

4. 记录系统/Python/包版本、安装命令、测试失败/跳过与耗时、夹具 hash。若失败，先定位环境与路径，不修改 P2 历史 gold、失败记录或预算账本。
5. 按 README 的新目录身份模式交互创建管理员、研究者和审核者；口令不进入命令参数、文件、截图或 Git。浏览器亲自走资料导入、冻结项目、指定审核者、两次审批、修订后重审、权限审计、ZIP 下载及独立复核。确认 ZIP 实际落到操作系统下载目录，另检查窄屏。仅用有权资料；常规演示用助手原创合成资料，不调用收费 API。

留存测试输出、页面步骤、ZIP 复核、失败案例与脱敏截图。分别评价工程复现、工具安全、检索、工作流、报告内容；工程通过不等于学校当届验收或真实内容质量通过。学生须亲自操作并解释关键代码，助手演示不算独立能力证明。
