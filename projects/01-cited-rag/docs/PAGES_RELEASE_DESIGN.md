# P1 V2-E2 GitHub Pages发布设计

- 文档状态：`accepted；e2b-implemented；public-verified`
- 版本：`0.3`
- 日期：`2026-08-28`
- 前置基线：V2-E1本地静态证据制品完成，`446 passed`，本地HTTP 200
- 当前范围：冻结Pages制品、workflow、权限、URL、发布验证和回滚；不实施公开发布

## 1. 决策摘要

V2-E2继续使用GitHub Pages项目站，只发布`portfolio-site/p1/`静态制品。发布路径拆成两个审批切片：

1. **V2-E2A本地发布就绪**：在工作树新增静态制品验证脚本和`.github/workflows/p1-pages.yml`，执行离线合同；不push、不触发Actions、不更改Pages设置。
2. **V2-E2B公开激活**：经再次批准后，才允许push候选分支、创建或更新PR、检查远程验证、合并到`main`、把Pages Source设为GitHub Actions、运行部署并验证公开URL。

拆分原因：workflow文件本身可本地审查；push、PR、合并、Pages设置和公开URL是不同外部副作用。E2A通过不自动授权E2B。

## 2. 已核验事实与未知量

### 2.1 2026-08-28已核验

- 远程仓库：`https://github.com/rorinhoon-bot/ai-application-portfolio`。
- 仓库可匿名读取，visibility为public；默认分支为`main`。
- GitHub Pages项目站默认URL形状为`https://<owner>.github.io/<repository>/`。
- 本项目预期URL形状为`https://rorinhoon-bot.github.io/ai-application-portfolio/`；首次部署成功前不得写成实际在线URL。
- GitHub官方文档允许自定义Actions workflow上传Pages artifact，再由独立deploy job发布；PR可只构建不部署。
- `portfolio-site/p1/`当前9个文件、233,881 bytes，入口`index.html`位于artifact根目录，远低于Pages 1 GB站点上限。
- 仓库根没有repository-wide `LICENSE`文件。作者可发布自有内容，但外部复用权限不明确；E2不虚构开源许可证。若以后希望他人复用代码，另行选择许可证。

### 2.2 执行前仍需确认

- 当前Pages是否已启用及Source实际值，需要E2B时用有权限账户查看；设计阶段不猜测。
- 仓库Actions/Pages环境保护规则、分支保护和PR合并权限，需要E2B时只读预检。
- 实际`page_url`、deployment ID、Actions run ID、线上响应头和资源URL，只能在首次真实成功后记录。

## 3. 公开制品合同

唯一artifact根目录：`portfolio-site/p1/`。

允许公开：

- `index.html`、`README.md`、`evidence-manifest.json`。
- `assets/*.css`、`assets/*.js`、固定JSON和两张录制截图。
- 页面已有的GitHub仓库与Python官方文档外链。

禁止公开：

- `.env`、API Key、Cookie、Authorization header、私钥、Git凭据。
- 原始HTML语料、模型文件、Qdrant数据/snapshot、Docker配置密钥、未脱敏日志。
- 符号链接、设备文件、隐藏文件、绝对本机路径、artifact根之外文件。
- FastAPI、Qdrant、MiMo地址或任意实时问答入口。

发布验证器必须：

1. 调用`export_portfolio_evidence.py --check`确认固定证据未漂移。
2. 拒绝符号链接、非普通文件、隐藏文件和路径越界。
3. 使用扩展名allowlist：`.html/.md/.json/.js/.css/.png`。
4. 要求根`index.html`存在；文件数不超过32，总大小不超过1 MiB，单文件不超过256 KiB。
5. 复核CSP、无远程子资源、无运行时网络API、无表单/iframe、无绝对本机路径和敏感模式。
6. 输出确定性JSON清单，记录相对路径、字节数、SHA-256和总量；默认拒绝覆盖已有报告。

## 4. URL与子路径合同

- artifact根直接映射项目站根；不再增加`/p1/`层。
- 预期URL形状：`https://rorinhoon-bot.github.io/ai-application-portfolio/`。
- 页面内部资源继续使用相对URL，例如`assets/styles.css`；不得写死`/assets/...`。
- 外链只允许编译时固定的`https://github.com/rorinhoon-bot/ai-application-portfolio`与`https://docs.python.org/...`。
- 不配置自定义域名，不加入`CNAME`；以后使用自定义域名需独立DNS与域名所有权设计。
- workflow只把`actions/deploy-pages`的`page_url`作为候选实际URL；仍须HTTP 200与内容/hash检查后才能写入文档或简历。

## 5. 官方Action供应链冻结

只允许以下GitHub官方Action，全部固定完整commit SHA：

- `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1`（v7.0.1）。
- `actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97`（v7.0.0）。
- `actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9`（v5.0.0）。
- `actions/deploy-pages@cd2ce8fcbc39b97be8ca5fce6e763baed58fa128`（v5.0.0）。

不使用第三方Action、floating tag、npm install、Jekyll插件、PAT或repository secret。`actions/configure-pages`不需要：当前站点无构建器，全部内部资源为相对URL；省去该Action可缩小供应链面。

## 6. 精确workflow草案

E2A实施时创建`.github/workflows/p1-pages.yml`，语义必须与下列草案一致。实现后的workflow还需由合同测试解析关键字段，不能只靠文本搜索。

```yaml
name: p1-pages

on:
  pull_request:
    paths:
      - ".github/workflows/p1-pages.yml"
      - "portfolio-site/p1/**"
      - "projects/01-cited-rag/data/*.json"
      - "projects/01-cited-rag/docs/images/cli-demo.png"
      - "projects/01-cited-rag/docs/images/streamlit-cited-answer.png"
      - "projects/01-cited-rag/scripts/export_portfolio_evidence.py"
      - "projects/01-cited-rag/scripts/validate_pages_artifact.py"
  push:
    branches: ["main"]
    paths:
      - ".github/workflows/p1-pages.yml"
      - "portfolio-site/p1/**"
      - "projects/01-cited-rag/data/*.json"
      - "projects/01-cited-rag/docs/images/cli-demo.png"
      - "projects/01-cited-rag/docs/images/streamlit-cited-answer.png"
      - "projects/01-cited-rag/scripts/export_portfolio_evidence.py"
      - "projects/01-cited-rag/scripts/validate_pages_artifact.py"
  workflow_dispatch:

permissions: {}

concurrency:
  group: p1-pages-${{ github.ref }}
  cancel-in-progress: false

jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read
    steps:
      - name: Checkout
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          persist-credentials: false
      - name: Set up CPython 3.14.3
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
        with:
          python-version: "3.14.3"
      - name: Check deterministic evidence
        run: python projects/01-cited-rag/scripts/export_portfolio_evidence.py --check
      - name: Validate exact Pages artifact
        run: python projects/01-cited-rag/scripts/validate_pages_artifact.py
      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9
        with:
          path: portfolio-site/p1
          retention-days: 1

  deploy:
    if: github.ref == 'refs/heads/main' && github.event_name != 'pull_request'
    needs: verify
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy GitHub Pages
        id: deployment
        uses: actions/deploy-pages@cd2ce8fcbc39b97be8ca5fce6e763baed58fa128
```

## 7. 权限、触发与身份边界

- workflow顶层`permissions: {}`；所有未显式权限均为`none`。
- `verify`只拿`contents: read`；checkout设置`persist-credentials: false`。
- `deploy`不checkout源码，只拿`pages: write`与`id-token: write`。
- `id-token: write`只允许请求OIDC token，不授予其他资源写权限。
- 不使用`pull_request_target`、`repository_dispatch`、schedule或外部webhook。
- PR和非`main`手工运行只能执行`verify`；`deploy`必须同时满足`refs/heads/main`且不是PR。
- `cancel-in-progress: false`，避免中途取消已开始的发布；同ref发布串行。
- 现有`p1-ci.yml`保持`contents: read`，不增加Pages权限。

## 8. E2B执行顺序与发布门

1. 确认本地工作树干净、E2A提交存在、完整离线测试通过。
2. 只读检查远程仓库仍为public、默认分支仍为`main`、Action SHA仍对应核验release。
3. 经批准后push `codex/p1-production-rag-v2`；创建PR到`main`，记录分支和提交SHA。
4. PR只允许`verify`；检查artifact清单、权限、Action来源和全部远程结果。
5. PR未通过则停止，不合并、不启用Pages、不手工绕过门禁。
6. PR通过后，合并与Pages Source=`GitHub Actions`属于公开副作用；只有E2B批准覆盖这些动作时才执行。
7. `main`部署成功后，记录Actions run ID、deployment ID、批准提交、`page_url`和artifact清单SHA-256。
8. 在线验收：根URL、CSS、JS、JSON、两张图片均200；无第三方子资源或运行API；页面仍显示“录制证据 · 非实时推理”。
9. 以浏览器检查桌面和360px窄屏、键盘tab、外链、安全标签；保存真实公开截图。
10. 全部门通过后，才更新README、STATUS、DECISIONS和求职链接，并明确静态录制证据。

## 9. 失败与回滚

- PR verify失败：保留日志，修复新提交；不合并、不启用Pages。
- `main`部署失败：保留失败run和artifact；上一个成功deployment继续作为回滚基线。首次部署失败时没有可宣传URL。
- 发布后内容错误：用新提交恢复到最后一个已验证site tree并重新部署；禁止force-push或删除失败证据。
- 泄密怀疑：先停止公开。禁用Pages或更改Source是外部设置变更，需用户授权；同时撤销受影响凭据并保留事件记录。
- 停止公开：Settings > Pages中撤销发布源或使用官方unpublish流程；不删除Git历史来隐藏事故。

## 10. 设计阶段验收与外部副作用

设计完成条件：

- 官方Pages、workflow、权限和Action release来源已于2026-08-28复核。
- 默认分支、仓库可见性、预期URL形状、制品范围和大小已记录。
- Action完整SHA、workflow草案、两阶段审批、发布后验收和回滚已冻结。
- 离线合同锁定以上边界；P1全量测试、`compileall`、`pip check`与`git diff --check`通过。

设计阶段禁止：创建workflow、push、PR、合并、远程Actions、Pages设置、deployment、公开URL、secret、模型调用、Qdrant写入、Docker修改或费用。

## 11. 后续实施批准边界

### 11.1 V2-E2A本地发布就绪

另行批准后，才允许：

- 新增`.github/workflows/p1-pages.yml`和标准库`validate_pages_artifact.py`。
- 新增workflow结构、artifact清单、安全与离线合同测试。
- 在本地运行验证并提交到当前V2分支。
- 仍禁止push、PR、远程Actions、Pages设置、公开URL和云资源。

建议批准语句：

`批准按 PAGES_RELEASE_DESIGN.md 第11.1节执行 V2-E2A`

### 11.2 V2-E2B公开激活

E2A通过后，必须先提交：本地提交SHA、计划push分支、PR标题、远程门禁、Pages设置动作、实际公开内容清单、回滚提交和停止公开步骤。只有再次批准，才允许执行第8节外部动作。

E2B批准不包含E3实时服务、域名购买、自定义DNS、MiMo调用或任何收费云资源；本次批准结果不扩大这些边界。

## 12. 官方来源

- GitHub Pages项目站URL与静态托管：<https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages>
- Pages发布源与自定义workflow：<https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site>
- 自定义Pages workflow：<https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages>
- Pages限制：<https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits>
- workflow权限语义：<https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax>
- `GITHUB_TOKEN`最小权限：<https://docs.github.com/en/actions/concepts/security/github_token>
- Actions安全：<https://docs.github.com/en/actions/reference/security/secure-use>
- Action release：<https://github.com/actions/upload-pages-artifact/releases>、<https://github.com/actions/deploy-pages/releases>

## 13. V2-E2A实施结果（2026-08-28）

- 已创建`.github/workflows/p1-pages.yml`；实现语义与第6节一致，四个官方Action完整SHA、job级最小权限、PR不部署和仅`main`部署由结构合同锁定。
- 已创建标准库`scripts/validate_pages_artifact.py`。默认只向stdout输出确定性JSON；显式`--write-report`只可写固定项目内报告，已有目标文件时拒绝覆盖。
- 机器证据`data/pages-release-readiness-report.json`绑定当前9文件、233,881 bytes及全部逐文件SHA-256；测试要求该报告与实时重算完全一致。
- 安全合同覆盖符号链接、隐藏/非普通文件、路径越界、扩展名与大小上限、CSP、远程子资源、网络API、表单/iframe、本机绝对路径和疑似secret赋值。
- 本地验收为`471 passed, 1 skipped`；跳过项仅因当前Windows会话不能创建测试用符号链接，校验器仍显式拒绝符号链接。`compileall`、`pip check`、证据`--check`、artifact验证和Git边界均通过。
- 外部副作用保持0：没有push、PR、远程Actions、Pages设置、deployment、公开URL、云资源、依赖安装、MiMo调用、Qdrant写入或Docker修改。
- 第11.2节已按批准执行；实际远程结果与二次证据回填见第14节。

## 14. V2-E2B实施结果（2026-08-28）

- 学习者明确批准公开`2041a6a`全部144个文件并继续E2B；候选分支已push，PR #1保留评审和失败修复历史。
- PR远程门禁最终全部通过。跨平台修复只处理换行、CI对本地模型资产的错误依赖和冻结评估输入，不改变检索/回答指标或安全门。
- PR #1以squash合并到`main`，merge commit为`0748abfa2f0ec579179ca8095513c0ac3462a2b1`。
- Pages Source已设为GitHub Actions且HTTPS强制开启。首次Pages run为`33173696014`，deployment ID为`6141599225`，公开URL为`https://rorinhoon-bot.github.io/ai-application-portfolio/`。
- `main` CI run `33173695996`的Windows离线合同与Linux API镜像合同均为`success`。
- 根页面、CSS、JS、证据JSON和两张截图均HTTP 200，六个SHA-256逐项匹配本地首次发布制品；桌面与360px浏览器视觉检查通过。
- 首次发布页面仍带E2A时期“Pages尚未启用”文案。该内容错误不删除首次deployment；使用独立补充提交更新发布状态，再走相同PR、CI、Pages与在线hash门。
- 脱敏机器证据见`data/pages-public-release-report.json`。E3实时服务、域名、DNS、MiMo调用和收费云资源仍未批准。
