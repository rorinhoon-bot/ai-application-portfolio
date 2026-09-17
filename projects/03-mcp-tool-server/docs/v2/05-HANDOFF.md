# P3 V2 开发交接

日期2026-09-16。Git `codex/p3-mcp-v2`，HEAD `dcb164e95059b060ffd6aebbaa093a7626177614`。既有572条改动见根 `docs/integration/baselines/20260916-start/worktree.json`，P1/P3在进入时无改动。旧文档的main/commit要求为历史，不覆盖本轮禁止暂存/提交/push的指令。

A已完成：根 `docs/integration/P1-READONLY-ACCEPTANCE.md`；P1定向74 passed，无HTTP/容器证据。P2以 `docs/v2/20-FINAL-ACCEPTANCE-AUDIT.md` 为准，266 passed为历史工程证据；内容失败、417/500分和109/109调用容量必须保留。

B0完成：阅读P3合同、server/index/search、安全读写、旧测试/评估/交接，实际V1基线240 tests，9 skip。缺口：未严格structuredContent/outputSchema，索引错误被吞为空，读时不重验hash，读工具未统一审计。当前目标B1。V2设计见同目录01～04；暂未通过V2验收，不开始C业务代码。

运行使用P3本地 `.venv/Scripts/python.exe`，标准unittest。测试只创建自己的临时目录；任何旧数据库、身份文件、服务、.env均不碰。不安装包。更新本文件记录每阶段命令与结果。

B3完成：最终263 tests/9 skip/31.942s；16/16真实stdio固定评估，38收据；旧40/40和8/8，pip check通过。V2离线验收通过，见07-ACCEPTANCE.md，允许按用户顺序进入C。SDK REQUEST_TIMEOUT另有回归；无依赖更改。

2026-09-17整合接力：P3验收后已进入codex/graduation-integration，HEAD未变；C最终18/18与P2全套266项回归通过。整合业务独立位于integrations/graduation，详见根docs/integration/ACCEPTANCE.md。P3业务代码此后未变，V2仍254通过/9skip；无真实API、提交或发布。
