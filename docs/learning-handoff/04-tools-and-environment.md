# 工具与开发环境

检测日期：2026-07-27。

## 当前机器

| 项目 | 检测结果 | 说明 |
|---|---|---|
| 操作系统与终端 | Windows + PowerShell | 当前工作目录位于 H 盘 |
| Node.js | `v24.16.0` | 可用 |
| npm | `11.13.0` | `npm.cmd` 可用；PowerShell 直接执行 `npm` 被执行策略拦截 |
| Git | `2.54.0.windows.1` | 可用 |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU | 8188 MiB 显存 |
| NVIDIA Driver | `610.74` | `nvidia-smi` 可用 |
| Python | 当前不在 `PATH` | `python`、`py`、`python3` 均未找到 |
| Docker | 当前不可用 | `docker` 命令未找到 |

## 当前学习目录

路径：

```text
H:\暑假学习\编程学习\学习网站各节点学习
```

只读盘点结果：

- 当前目录不是 Git 仓库。
- 创建交接包前仅发现代理配置备份和代理脚本。
- 未发现 Python、RAG、Agent、LoRA、MCP 等练习源码。
- 交接包创建在 `handoff/`，不修改原有文件。

## Python 是否必须加入环境变量

不强制，但推荐让 Python 可被命令行找到。

有三种使用方式：

1. Python 安装目录加入用户 `PATH`，之后可直接运行 `python`。
2. 不加入 `PATH`，每次使用完整路径，例如：

   ```powershell
   H:\Python\python.exe --version
   ```

3. 在项目中使用虚拟环境；但创建虚拟环境时仍需先找到基础 Python。

推荐方案：

- Python 安装到 H 盘的固定目录。
- 把 Python 主目录和 `Scripts` 目录加入“用户 PATH”，无需修改系统级 PATH。
- 每个作品再创建自己的 `.venv`，项目依赖不装进全局 Python。

示例结构：

```text
H:\DevTools\Python\
H:\暑假学习\编程学习\ai-application-portfolio\.venv\
```

安装 Python 前应根据首个作品使用的库确认兼容版本，不在本交接阶段安装。

## Docker 计划

用户愿意安装 Docker，并希望尽量使用 H 盘。

注意事项：

- Docker Desktop 程序、WSL 后端和容器数据位置是不同概念。
- 即使程序安装位置可调整，部分系统组件仍可能使用系统盘。
- 真正占空间的镜像、容器和虚拟磁盘应优先配置到 H 盘。
- 安装属于系统级变更，应在作品集环境初始化阶段单独确认安装方式和目标目录。

当前第一阶段不安装 Docker。P1 或本地模型部署确实需要时再处理。

## 待配置清单

- 安装可被命令行访问的 Python。
- 创建作品集项目 `.venv`。
- 初始化 Git 仓库。
- 建立 `.gitignore`，排除 `.env`、`.venv/`、缓存和模型文件。
- 按首个项目需求安装最少依赖。
- 后续需要容器化时安装 Docker，并把主要数据迁移到 H 盘。
- API Key 只放 `.env` 或系统环境变量，不写入代码、文档和 Git。

