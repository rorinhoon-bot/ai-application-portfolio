# GitHub 发布前审计与截图清单

更新时间：2026-08-09。P0～P3 已上传至 GitHub `main`；本文保留发布审计、截图来源与后续维护清单，不包含 PR 或部署。

## 1. 审计结论

| 项目 | 代码/文档证据 | 公开描述状态 | 截图状态 | 发布判断 |
|---|---|---|---|---|
| P0 | README、架构、90 测试、10 例评估、学习手册齐全 | 已补展示区 | 已有真实离线验证输出图；CLI 成功生成图可选 | 可发布 |
| P1 | README、架构、检索评估、Streamlit 界面、学习手册齐全 | 已补展示区 | 已有 CLI 与 Streamlit 图 | 可发布；模型/索引恢复步骤必须保留 |
| P2 | README、完成审计、SVG 演示、144 测试、12/12 评估齐全 | 已补展示区 | 已有两张 SVG；可选补 UI/终端图 | 可发布 |
| P3 | README、完成审计、240 测试、40/40 评估、学习手册齐全 | 已补展示区与 `.env.example` | 已有真实 stdio 与 D-6 输出图 | 可发布；真实链接、多用户、公开部署必须标限制 |

## 2. 静态安全检查结果

- 根 `.gitignore` 忽略 `.env`、`.venv/`、Python 缓存、模型文件、私人数据和 P0/P1 本地输入输出。
- 受 Git 跟踪文件中未发现 `.env`、`.venv`、缓存字节码或超过 5 MiB 的文件。
- 本轮不读取、不提交任何本地 `.env`；它们仅作为被忽略的本机配置存在。
- 发布前仍要运行第 5 节的敏感信息扫描；扫描命中必须人工判断，不能直接把匹配内容复制进 issue 或聊天记录。

## 3. 必须保留的公开限制

### P0

- 真实模型评估有明确模型、数据和人工评分范围；不能说所有材料都可事实核验。

### P1

- 固定语料、BGE 模型与本地索引不全部进 Git；新机器须按 README 恢复。
- 真实模型问答需要用户自己的 API Key；不把 `.env` 推送。

### P2

- 使用原创虚构资料和确定性假工具；不证明真实技术选型结论。
- 无公开部署、无真实模型 API 成本数据。

### P3

- 使用原创虚构笔记；不读私人笔记、不调用真实模型。
- 真实 symlink/junction 专项、Linux/WSL 实机验证、真实多用户/OS 凭证绑定、跨主体审计隔离和公开部署均未完成。
- 回环 HTTP 不是公网服务；默认 transport 是本地 stdio。

## 4. 截图与演示清单

截图必须由真实命令或真实界面产生。截图前确认终端中没有用户名、绝对路径、API Key、Cookie、鉴权头、私人资料或完整异常栈。

| 编号 | 项目 | 要捕获什么 | 如何产生 | README 放置位置 |
|---|---|---|---|---|
| S0-1 | 根目录 | GitHub 首页项目矩阵 | 推送后网页截图 | 仓库首页可选，不必提交图片 |
| S1-1 | P0 | 已有离线测试与评估证据图 | 2026-08-09 真实 `pytest -q` 输出 + 已提交评估记录 | `projects/00-structured-content-generator/docs/assets/offline-verification.svg` |
| S1-2 | P0 | 可选：CLI 成功结构化 JSON 摘要 | 使用原创材料和本人 API Key；不可截图 Key | 同上 |
| S2-1 | P1 | 已有 Streamlit 首页、问题、引用卡片 | 已提交 `docs/images/streamlit-cited-answer.png` | README 已引用 |
| S2-2 | P1 | 已有 CLI 真实结果 | 已提交 `docs/images/cli-demo.png` | README 已引用 |
| S3-1 | P2 | 已有工作流 SVG | 已提交 `demo/assets/workflow-overview.svg` | README 已引用 |
| S3-2 | P2 | 已有离线终端演示 SVG | 已提交 `demo/assets/offline-demo-terminal.svg` | README 已引用 |
| S4-1 | P3 | 已有 stdio 演示 8/8 结果 | 2026-08-09 真实 `demo/mcp_stdio_demo.py` 输出 | `projects/03-mcp-tool-server/docs/assets/offline-stdio-demo.svg` |
| S4-2 | P3 | 已有 D-6 评估 40/40 摘要 | 同一真实运行证据图 | 同上 |
| S4-3 | P3 | `notes://service-info` 或 Tool 列表脱敏结果 | 真实本地 MCP 演示 | 同上 |

捕获完成后：

1. 图片只保留必要区域，PNG 优先，单张建议小于 1 MiB。
2. 在项目 README 使用相对路径插入图片，并写清命令和预期结果。
3. 对应命令再次运行，确认截图不是过期结果。
4. 单独检查 `git diff --check` 和敏感扫描后才提交。

## 5. 发布前最终命令

在仓库根目录运行。不要用 `git add -A`，因为工作区可能有不属于发布范围的文件。

```powershell
# 只读状态检查
git status --short
git diff --check

# 跟踪文件敏感模式扫描；命中后人工检查上下文，不回显真实秘密
rg -n -i "(sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|bearer[[:space:]]+[A-Za-z0-9._-]{10,}|api[_-]?key[[:space:]]*[:=])" .

# 确认忽略规则
git check-ignore -v projects/00-structured-content-generator/.env
git check-ignore -v projects/01-cited-rag/.env
```

然后按各项目 README 复跑测试和评估。若 P1 需要恢复模型或调用真实 API，先确认个人预算与 API Key 边界；不要为了截图临时使用真实私人资料。

## 6. 本轮已知工作区隔离

发布本轮文档时，必须排除：

- `projects/02-agent-research-workflow/` 下既有的 6 个修改文件；它们不属于本次 GitHub 展示材料。
- `.workbuddy/` 未跟踪目录。

公开发布前必须由用户明确确认最终 Git 远端、分支策略和 PR 策略。
