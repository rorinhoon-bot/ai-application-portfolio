# 环境初始化记录

最后核验日期：2026-07-28。

## 已检测

- Windows + PowerShell
- Node.js `v24.16.0`
- npm `11.13.0`
- Git `2.54.0.windows.1`
- RTX 4060 Laptop GPU，8GB 显存
- Python `3.14.3`，64 位，`python` 和 `py` 均可从 CMD 与 PowerShell 调用
- 基础 Python 运行时位于 `%LOCALAPPDATA%\Python\`
- pip `25.3`
- Docker 当前无法从命令行找到

## Python

复用现有 Python `3.14.3`，不重复安装，不修改系统级 `PATH`。

P0 已创建项目本地虚拟环境：

```text
projects\00-structured-content-generator\.venv
```

核验结果：

- `.venv` 使用 Python `3.14.3`。
- `.venv` 中 pip 为 `25.3`。
- `sys.prefix` 与 `sys.base_prefix` 不同，虚拟环境隔离有效。
- P0 已安装并固定生产与开发依赖，90 个自动测试通过，`pip check` 通过。
- 仓库 `.gitignore` 已忽略 `.venv/`。

使用原则：

- 每个 Python 作品使用自己的项目本地 `.venv`。
- 所有项目依赖只安装到对应 `.venv`。
- 优先使用 `.venv\Scripts\python.exe -m pip`，避免调用错误的 pip。
- PyCharm 选择对应 `.venv\Scripts\python.exe` 作为项目解释器。
- 激活虚拟环境不是必需步骤；不为激活脚本修改 PowerShell 执行策略。
- 若后续依赖不支持 Python `3.14`，再单独评估其他 Python 版本，不提前重装。

## Docker

P0 不安装、不使用 Docker。

确实需要容器化时：

- 单独确认 Docker Desktop 与 WSL 要求。
- 尽量把镜像、容器和虚拟磁盘数据放到 H 盘。
- 接受部分系统组件可能仍使用系统盘。
- 安装完成后验证 `docker version` 和一个最小容器。

## API Key

- 真实值写入本地 `.env`。
- 仓库只提交 `.env.example`。
- 不在截图、日志、测试夹具和 README 中放真实值。
- P0 已选择 MiMo，模型为 `mimo-v2.5`；真实 API Key 只保存在本地 `.env`。
- 后续项目选择供应商或产生新的 API 费用前，必须先获得用户确认。
