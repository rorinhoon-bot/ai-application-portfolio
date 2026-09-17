# P3 V2 架构

## 分层

`stdio Client -> MCP严格合同 -> 审计开始 -> 策略/参数验证 -> 冻结笔记目录或显式写意图适配器 -> 输出验证 -> 审计完成 -> MCP结果`。

新增 `mcp_notes.v2` 模块，不改变V1底层批准/原子发布协议。SDK固定 `mcp==2.0.0`、`mcp-types==2.0.0`，复用已安装 `pydantic==2.13.4`、`jsonschema==4.26.0`；不新增依赖。P3 Python 3.13.14，与P1/P2进程隔离。

## 数据与权限

启动时安全读取登记文件原始字节，校验UTF-8/字节长度/SHA-256，再冻结有限内存快照。后续工具不读取用户指定路径；`note_id`不是权限凭证，只能查当前启动快照。快照更新必须重启服务并重新批准研究范围。

严格版本化响应：状态、稳定错误码、调用ID、快照hash、结果列表/单文档/意图。禁止未知输出字段。成功仅由确定性程序生成；JSON文本和structuredContent同一对象序列化。

默认只读启动配置不初始化TasksStore。可选写只登记意图，不代批。复用 `ServerConfig`/RuntimeIdentity与V1 `TasksStore`；不可将模型字段当subject。审计失败前不执行写；写后审计失败只能报告未知/审计失败，不能宣称回滚。

## 审计和恢复

审计落到部署方预创建的独占目录，使用既有安全no-replace发布，每个调用开始/结束一份JSON。调用ID由服务端UUID生成，包含协议版本、快照hash、参数规范hash、工具固定名、结果hash和稳定码，不写正文、真实用户身份或原始异常。并发调用互不覆盖。开始无完成表示执行结果未知；只读可重放，写必须先查可信Host状态。此审计非防管理员篡改，需由整合层绑定收据hash。

读工具从有界内存执行。Client为每次MCP操作设置超时，超时仅只读可尝试一次恢复；服务器业务协程亦有期限。进程启动/卡死由外层受控子进程超时终止；禁止用线程超时假装杀死底层写入。写意图同步、无自动重试，最终任务发布仍由Tool外控制器完成。

## 规范依据

[MCP Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)：发布inputSchema/outputSchema，structuredContent和兼容文本，业务失败isError。以已安装SDK签名与真实stdio回归验证适配；不改依赖追逐最新版。工具注解不是授权系统。

## 已知平台边界

Windows原生句柄读与no-replace写在本机回归。历史真实链接测试9项跳过，不能算通过；Linux/WSL、多OS用户、远程HTTP部署不属于V2验收范围。V1 HTTP兼容测试使用测试自建回环端口，不连接既有服务；V2只用stdio。
