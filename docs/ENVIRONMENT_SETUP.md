# 环境初始化计划

当前仅制定计划，不在项目创建阶段安装软件。

## 已检测

- Windows + PowerShell
- Node.js `v24.16.0`
- npm `11.13.0`
- Git `2.54.0.windows.1`
- RTX 4060 Laptop GPU，8GB 显存
- Python 当前无法从命令行找到
- Docker 当前无法从命令行找到

## Python

Python 不强制加入系统级环境变量，但需要一种稳定调用方式。

推荐：

1. 安装到 H 盘固定目录。
2. 把 Python 主目录和 `Scripts` 加入用户 `PATH`。
3. 在仓库根目录创建 `.venv`。
4. 所有 Python 依赖安装到 `.venv`。

不加入 `PATH` 也能用完整路径运行，但日常操作更麻烦。

安装前先确认首个项目依赖支持的 Python 版本。

## Docker

P0 不需要 Docker。P1、P2 也可先本地运行。

确实需要容器化时：

- 单独确认 Docker Desktop 与 WSL 要求。
- 尽量把镜像、容器和虚拟磁盘数据放到 H 盘。
- 接受部分系统组件可能仍使用系统盘。
- 安装完成后验证 `docker version` 和一个最小容器。

## API Key

- 真实值写入本地 `.env`。
- 仓库只提交 `.env.example`。
- 不在截图、日志、测试夹具和 README 中放真实值。

