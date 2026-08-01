# P2 完成审计

- 审计版本：v0.1
- 日期：2026-08-01
- 对照标准：仓库根目录 `docs/PROJECT_STANDARDS.md`
- 当前结论：7 类工程与展示标准已有证据；PRD 人工报告质量量表尚未执行，P2 保持 `in_progress`

## 1. 问题与用户：PASS

- `README.md` 用一句话说明问题，并列出目标用户、输入、输出和不处理范围。
- `docs/PRD.md` 固定场景、目标用户、非目标和可量化验收标准。
- 当前范围明确为原创虚构资料上的离线工作流可靠性，不声称现实技术选型能力。

## 2. 可运行：PASS

- `README.md` 给出 Windows、CPython 3.14、创建 `.venv`、安装锁定依赖和 `pip check` 命令。
- `.env.example` 完整列出当前两个环境变量；无 API Key。
- `requirements.txt` 与 `requirements-dev.txt` 固定全部依赖版本。
- `scripts/verify_environment.py` 校验直接依赖版本、最小 LangGraph 图和 SQLite 关闭重开恢复。

边界：最终审计不重新下载依赖；P2 独立 `.venv` 已在依赖阶段从锁定 wheel 建立并验证。

## 3. 代码质量：PASS

- 状态、图、工具合同、假工具、证据评估、草稿、审校、人工返修、导出、观测、评估和演示按职责拆分。
- 运行时依赖与 checkpoint 业务状态分离。
- 错误只持久化稳定错误码和安全摘要。
- 直接和传递依赖均精确固定；依赖原因、许可和 Python 兼容性见 `docs/DEPENDENCIES.md`。

## 4. 测试：PASS

- 普通测试覆盖成功、缺失需求、非法输入、工具瞬时/确定性失败、证据不足、自动与人工返修上限、人工拒绝/取消、checkpoint 恢复和导出冲突。
- 高风险导出覆盖人工批准、revision/hash 绑定、路径规范化、symlink/junction 拒绝、不可覆盖发布和崩溃窗口重放。
- `tests/conftest.py` 默认阻断网络。
- 最近一次完整 pytest 结果：`144 passed`。

## 5. AI 评估：PASS（工作流可靠性范围）

- 固定输入：`evals/workflow-v1.json`，12 个成功、失败和人工介入案例。
- 固定金标准：`evals/gold/workflow-v1-gold.json`。
- 固定来源：10 份原创资料、40 个证据章节和内容哈希快照。
- 固定基线：`evals/results/workflow-v1-baseline.json`。
- 模型、Prompt、参数和数据版本的适用状态集中记录在 `docs/EVALUATION_DATA.md` 12.1；当前模型和 Prompt 均不适用，不伪造版本号。
- `--check` 使用同一固定集真实执行 LangGraph 后逐字节回归；`expected` 不驱动执行。
- 基线：案例、路径和重试/停止 `12/12`，引用 `10/10`，恢复 `1/1`，无证据声明 `0/10`，未批准导出和权限扩大均为 `0`。

该 PASS 只表示确定性工作流评估合格，不表示 PRD 人工内容质量量表已通过。

## 6. 安全：PASS

- 无真实密钥、私密数据、真实供应商响应或 checkpoint 文件进入 Git。
- 模型或夹具生成的 URL、路径、命令和工具参数均不直接信任。
- 来源加载和报告导出有 allowlist、规范路径、路径穿越及 symlink/junction 防护。
- 资料为原创虚构数据，许可标记为项目原创合成夹具；无真实个人或机密数据。
- 普通测试、评估和演示均无网络、真实模型、下载或费用。

## 7. 展示：PASS

- `README.md` 包含功能、边界、架构图、安装、演示、测试、评估和限制。
- `demo/assets/` 有真实输出重建的终端 SVG 和显式工作流 SVG。
- `demo/generated/` 有人工批准路径的固定 Markdown 报告和演示 manifest。
- `demo/FIVE_MINUTE_TALK.md` 与 `LLH_Study.md` 支持五分钟讲解、面试问答和自测。

## 8. 完成检查：BLOCKED

PRD 要求人工报告量表平均分至少 `4/5`。当前没有真实人工评分，不能由自动测试、确定性夹具或 AI 编码助手代填。

解除阻塞：

1. 人工阅读 `demo/generated/3cb6e874c988bd2795164fbde10e882e1093a536bb0a01d40f180cd097f24dd0.md`。
2. 按 `evals/HUMAN_REPORT_RUBRIC.md` 对五个维度各给 1～5 分，并写一句主要问题。
3. 平均分达到 `4.0`：保存结果，重跑全部验证，再把 P2 与作品集计划标记为完成。
4. 平均分低于 `4.0`：保持 `in_progress`，记录失败分类；另建修订版本，不修改 `workflow-v1` 金标准迎合评分。
