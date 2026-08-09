# D-5 实现记录：本地 Host 支持面与传输扩展

## 结论

默认传输仍为 `stdio`。仅当部署受控环境显式设置 `MCP_NOTES_TRANSPORT=streamable-http` 时，Server 才启用 MCP SDK v2 自带的 streamable-HTTP；只接受 `MCP_NOTES_HOST=127.0.0.1` 或 `::1`，固定端点 `/mcp`，端口须为 `1..65535`。

## 安全边界

- `sse`、未知 transport、空 transport、`0.0.0.0`、局域网地址与不合法端口一律以 `invalid-arguments` 失败关闭。
- 不新增依赖；复用已锁定 SDK 所带 `starlette`、`uvicorn`、`httpx2`。
- HTTP 只允许本机回环测试和本机 Client；不访问公网，不公开部署。
- Tool 和 Resource 不变；`approve` / `reject` / `cancel` 仍只在 Tool 外可信 Host 中调用。
- `subject`、`correlation_id`、PUBLISHING 状态机、D-2 句柄式 no-replace 发布完全复用，未被 HTTP 请求字段授权或覆盖。

## 验收

`tests/test_d5_transport.py` 覆盖默认 stdio、拒绝公网监听/坏端口/legacy SSE，以及真实本机回环 streamable-HTTP MCP Client 的 `list_tools`、`create_task` 待确认路径。该测试只连接 `127.0.0.1`，没有真实链接、模型调用或外网请求。

当前总测试为 239 项（230 通过 + 9 默认跳过）；C 阶段 23 项 stdio 集成、6 项入口、评估 11/11 与演示 8/8 均保留。公开部署、第三方网络边界审计、真实多用户仍 blocked-until-approved。
