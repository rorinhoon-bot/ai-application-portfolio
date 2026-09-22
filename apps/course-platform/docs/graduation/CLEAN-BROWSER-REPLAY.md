# 干净源码三角色浏览器复演

2026-09-23，助手在提交 `5636d6d49665f78e403157be5f38472bd55b171f` 的 detached 干净源码工作树中，用全新忽略状态目录启动身份模式服务，并通过 Codex In-app Browser 实际操作研究者、审核者和管理员界面。未读取真实密钥，未调用网络或真实模型，未访问原项目数据库、容器、服务或 P2 账本。

## 实际流程

研究者导入两份明确标记为助手原创合成的资料，创建冻结项目和任务；审核者核对范围并批准；离线 worker 读取两条证据，执行 3 次脚本模型调用与 8 次只读 MCP 调用；研究者把摘要修订为“0/6 个支持单元，因此不作候选推荐”，并补充真实内容未验收等限制；审核者仅批准离线制品交付，明确不作内容质量认证。最终任务状态为 `COMPLETED`，真实模型调用和费用均为 0。

项目、任务和运行分别为 `project-27c76665323f48cda2f30010148dd9f0`、`task-7cf367c7ddad424bb0286b70d5310111` 和 `run-7cf367c7ddad424bb0286b70d5310111`。范围指纹为 `72b0abc438a3f12c0359ba0f7a37674a6bc616243cb467af20875a7341dcc136`；执行指纹为 `a5eae86dc32c4b1c2612af7e6f76664537cda30fbc46f671d69eda099db78bdc`。

管理员页面在浏览器流程结束时显示 26 条审计事件，包含资料导入、项目绑定、任务创建、两次审批、人工修订、完成、登录/退出、未认证拒绝和两次允许下载。随后本机 HTTP 持久化复核新增一次登录和一次允许下载，刷新后为 28 条。页面没有保存密码或会话令牌。

## 交付包复核

In-app Browser 的按钮请求和直接下载请求均到达服务端，管理员审计显示两条 `download ... allowed`。该浏览器会话没有在 Windows `Downloads` 目录产生可观察的新文件，因此不能宣称操作系统浏览器下载落盘通过。

为验证服务返回的实际字节，随后使用同一本机身份接口把响应保存到 Git 忽略的 `.runtime`，再运行：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/frozen_bundle_cli.py apps/course-platform/.runtime/ui-repro-20260923/research-delivery-browser-replay.zip
```

文件大小 22,753 字节，SHA-256 为 `33571823626c1d44f4280781e01cb415c733c014d7a4bb6f8ce998559b1b7df0`。独立 CLI 返回 `bundle_consistent: true`、`evidence_count: 2`、`scripted_model_calls: 3`、`real_model_calls: 0`、`mcp_calls: 8`、`cost_minor_units: 0` 和 `content_quality_passed: false`。结构化记录见 [repro-g4-browser.json](../results/repro-g4-browser.json)。

## 结论边界

本次补齐“最新已提交源码 + 隔离状态 + 三角色浏览器 UI”的复演证据，也证实浏览器下载请求经过授权、服务端交付包可保存并独立验签。仍未完成 Windows 浏览器默认下载目录落盘、新机器重装依赖、正式资料授权、教师当届条款、真人独立内容评分或学生本人独立讲解。`0/6` 是本次合成脚本结果，不是现实方案结论；人工批准、引用存在和包一致都不代表内容质量合格。
