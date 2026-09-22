# UI 第二版：研究空间

## 参考与选择

用户否定第一版视觉效果。本轮先检索GitHub，审阅官方仓库与技能说明：

- https://github.com/satnaing/shadcn-admin ：参考后台导航、内容层级和一致组件的思路。
- https://github.com/langgenius/dify ：相近的知识与工作流产品边界参考。
- https://github.com/nextlevelbuilder/ui-ux-pro-max-skill ：阅读SKILL.md中的排版、SVG图标、响应式、焦点与渐进披露建议。

不安装这些项目、技能CLI或依赖，不拷贝第三方源码/品牌/素材。只将设计原则应用于现有原生Web；本地frontend-design为本轮实际执行技能。远程技能仅作为设计参考，未运行其设计生成器，不宣称有数据库匹配结果。

## 设计方案与自检（实施前）

产品：用于阅读证据并作出审批的研究空间。主视觉围绕“问题、来源、决定”，弱化开发控制台感。第一版大段流程说明与深蓝背景抢占注意力，本版改成浅色导航、宽阅读面板和清晰的主操作。

颜色：画布#f8f9fb，面板#ffffff，正文#23272f，次级#626978，品牌#465dd9，边界#e7e9ef；绿色和琥珀只用于状态。中文用本地Microsoft YaHei UI/PingFang SC，英文Segoe UI；正文15px、阅读16px、标题28–32px，辅助不小于12px。8px间距基准，面板16px圆角，控件8px圆角。无外部字体、图标包或网络资源。

```text
浅灰侧栏 │ 面包屑                         离线状态
品牌     │ 标题 / 说明                    主操作
导航     │
新建研究 │ 知识页：[搜索 / 来源筛选]
         │ [资料列表 6条] [章节正文 / 定位 / 来源指纹]
运行说明 │
         │ 首页：[研究入口 + 可选问题模板]
         │       [真实任务统计] [最近研究]
```

自检：不加伪造图表、无效上传按钮或装饰数字。知识页以目录和阅读区为核心，不做同质指标卡墙。首页研究入口可操作，所有模板明确同一固定资料范围。报告强调段落层级，审批区保持可见，hash折叠但可查。

## 范围

仅web三文件及本应用设计/验收/交接记录。后端合同、权限、审批、P1/P2/P3、密钥和预算均不变。既有前端已备份到仓库私有Git审计目录。分支codex/course-platform-ui，HEAD9e2a77219ac7fbb83d28f6ca2f3e3756a4189201。

## UI V2（2026-09-19）

用户确认“浅色极简：清爽侧栏、文档阅读区、少量蓝色强调”。本轮完成原生前端视觉重构：浅色导航、研究问题入口与模板、真实任务统计、知识目录与阅读区、来源筛选、指纹视图、报告/审批/审计统一样式、手机与平板布局。辅助文字提升至至少12px；目录和阅读页签重绘后保留键盘焦点。

本轮仅改web三文件及本应用文档。原后端和测试文件SHA-256与上一轮delivery-review.json一致，P1/P2/P3与integrations没有代码差异。无新增依赖、远程技能安装、真实模型调用、commit或push。

验证：HTTPTests 6/6通过，3.455秒；命令为 `projects/02-agent-research-workflow/.venv/Scripts/python.exe -B -m unittest discover -s apps/course-platform/tests -p test_platform.py -k HTTPTests -v`。旧21/21完整回归是V1工程证据，本轮没有重复宣称新跑了21项。

浏览器行为：来源筛选Graph=3/Chain=3/全部=6；英文checkpoint与中文人工审批各2条；无匹配时0条且阅读区清空，键盘清空搜索恢复6条；选择目录同步正文与焦点；来源指纹可查。首页模板带入真实创建表单，新任务停在范围审批，脚本模型/MCP均0；取消需说明与勾选确认，取消后归档，审计保留。历史交付任务仍能展示6条证据、2次审批、8次MCP，评估页仍明确P2真实内容未通过。浏览器未记录应用脚本错误。

响应式：375×812与768×1024视口请求，浏览器扣除滚动条后的文档宽度分别360/754，scrollWidth与clientWidth相等；手机首页、知识页、报告页无整页横向溢出。桌面文档宽1266。已恢复默认视口。

证据：docs/results/ui-v2.json、docs/screenshots/ui-v2/；新版设计详见docs/UI-REFRESH.md。原截图、browser.json、evaluation.json和delivery-review.json保留为V1历史证据。此次UI验证不构成真实内容质量验收、完整无障碍认证或全新机器验收。

Git仍为codex/course-platform-ui，HEAD为9e2a77219ac7fbb83d28f6ca2f3e3756a4189201。原开发工作树仍为codex/graduation-integration、HEAD dcb164e95059b060ffd6aebbaa093a7626177614，668条全量status与任务前一致。main没有因此更新。
