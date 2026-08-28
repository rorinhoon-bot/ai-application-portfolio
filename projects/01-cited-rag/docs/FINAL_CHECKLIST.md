# 最终验收检查

- 日期：`2026-07-29`
- 状态：`passed`

## 问题与用户

- [x] README 一句话说明问题。
- [x] 目标用户、输入、输出和非目标明确。
- [x] PRD 含可检查验收标准。

## 可运行

- [x] 依赖精确固定，提供 `.env.example`。
- [x] 固定语料可离线恢复。
- [x] 固定模型可按 revision 和哈希恢复。
- [x] 本地索引可离线重建。
- [x] CLI 命令、目录和配置明确。
- [x] Streamlit 本地启动命令、目录和配置明确。
- [x] 仓库根目录双击启动脚本已实际启动验证。

## 代码、测试与安全

- [x] 导入、解析、切分、Embedding、索引、检索、回答、配置和 CLI 分责。
- [x] Streamlit 展示层复用问答服务，首次加载不初始化模型或索引。
- [x] 成功、非法输入、缺配置、外部错误、模型非法输出和文件安全路径有测试。
- [x] 普通测试不访问网络。
- [x] `.env`、展开语料、模型文件和本地索引不进入 Git。
- [x] 引用 URL、版本、章节和摘录由程序绑定。
- [x] 来源、许可、路径穿越和语料恢复规则有记录。

## AI 评估

- [x] 固定检索、拒答和回答评估集及报告已保存。
- [x] 模型、Prompt、参数、索引和数据版本可追踪。
- [x] 保存基线、优化结果、失败样例和人工忠实度。
- [x] 原版本比较0/3失败结果保留；双版本平衡检索后人工复核3/3。

## 展示

- [x] README 覆盖功能、架构、安装、运行、测试、评估和限制。
- [x] 有真实结果展示图。
- [x] 有真实 Streamlit 带引用回答图，并完成桌面与窄屏浏览器验收。
- [x] 有五分钟演示说明。
- [x] 有 `LLH_Study.md`。

## 待自动验证

- [x] 全部220项 pytest 通过。
- [x] `compileall` 通过。
- [x] `pip check` 通过。
- [x] `git diff --check` 通过。
- [x] Git 忽略边界复核通过。

## 结论

V1达到项目验收清单并保持completed。保留的小样本与机器可读`conflict`基线限制已在README、架构、评估和学习总结中公开。

## V2-B1 追加验收（2026-08-23）

- [x] Local/Server客户端工厂分离；URL、角色Key、timeout和profile严格校验。
- [x] Qdrant镜像固定tag与digest；容器非root、只读rootfs、最小capability并设置资源/日志上限。
- [x] 专用bridge只发布`127.0.0.1:6333`；6334/6335未发布。
- [x] 两个角色密钥分文件保存、不同且Git忽略；在线API只使用read-only key。
- [x] 1359-point离线迁移的维度、距离、payload、ID、过滤和self-query通过。
- [x] read-only读操作200，create/upsert/delete均403。
- [x] restart与无`-v`的down/up后身份与查询不漂移，两个named volume保留。
- [x] snapshot大小与SHA-256固定；上传恢复到临时collection全验通过，临时collection已删，活动collection不变。
- [x] Qdrant与P1`/readyz`均200；P1就绪检查未调用MiMo。
- [x] 历史报告可追踪；运行数据、snapshot、模型、语料、密钥和Server元数据不进入Git。
- [x] README、架构、PRD、决定、演示和`LLH_Study.md`已更新，并明确B1不等于API容器或公网生产。
- [x] 全部300项pytest、`compileall`、`pip check`和Compose解析通过；V1/V2-A测试零删除。

V2-B1达到本切片完成定义；P1 V2整体仍为in_progress。V2-B2、Hybrid/Rerank、可观测、CI与受控部署尚未完成。
