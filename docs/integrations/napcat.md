# NapCat OneBot 11 集成

LivingAgent 在 `/v1/adapters/napcat/ws` 提供宿主持有的 NapCat 平台适配器。NapCat 作为反向 WebSocket 客户端连接 LivingAgent、推送 OneBot 11 事件，并通过同一连接接收 API 操作。

## 已支持的垂直切片

- Bearer 令牌认证，并支持官方 `access_token` 查询参数作为后备。
- `X-Self-ID` 验证和逐帧 `self_id` 一致性检查。
- OneBot 11 私聊和群聊 `message` 事件。
- 数组消息和 CQ 码字符串消息。
- 为现有 LivingAgent TurnGate 识别群内 `@bot`。
- 只有 OneBot 操作响应成功后才逐单元记录投递。
- 同一会话收到新消息时取消未发送单元。
- 验证生命周期和心跳帧，但不送入认知流程。
- 并发事件处理和按 `echo` 关联的操作响应。
- 通过同一 WebSocket 执行 `send_private_msg` 和 `send_group_msg` 回复。
- 操作超时/失败隔离和结构化审计记录。

## LivingAgent 配置

设置强共享令牌。原始令牌使用 Pydantic `SecretStr` 表示，绝不会写入提示词或审计输出。

```bash
export LIVING_AGENT_NAPCAT_ENABLED=true
export LIVING_AGENT_NAPCAT_ACCESS_TOKEN='replace-with-a-long-random-token'
uv run uvicorn --app-dir src living_agent.app:app --host 127.0.0.1 --port 8000
```

可选限制：

```bash
export LIVING_AGENT_NAPCAT_ACTION_TIMEOUT_SECONDS=5
export LIVING_AGENT_NAPCAT_MAX_MESSAGE_CHARS=12000
export LIVING_AGENT_NAPCAT_MAX_FRAME_BYTES=1048576
export LIVING_AGENT_NAPCAT_MAX_IN_FLIGHT_EVENTS=16
```

启用 NapCat 却没有非空令牌时，启动验证失败。

## NapCat 配置

在 NapCat WebUI 中创建一个 **WebSocket 客户端**网络配置：

```json
{
  "name": "living-agent",
  "enable": true,
  "url": "ws://127.0.0.1:8000/v1/adapters/napcat/ws",
  "messagePostFormat": "array",
  "reportSelfMessage": false,
  "reconnectInterval": 5000,
  "token": "replace-with-a-long-random-token",
  "debug": false,
  "heartInterval": 30000
}
```

`token` 必须与 `LIVING_AGENT_NAPCAT_ACCESS_TOKEN` 一致。NapCat 会提供 Bearer 请求头和 `X-Self-ID`。优先使用请求头，因为查询字符串令牌可能被代理访问日志记录。服务位于不同容器时，将 `127.0.0.1` 替换为 LivingAgent 服务名或可访问主机。

## 身份与会话映射

NapCat 数据带命名空间，避免 QQ ID 与其他平台冲突：

```text
操作者:  napcat:<bot_qq>:qq:<sender_qq>
私聊:    napcat:<bot_qq>:private:<sender_qq>
群聊:    napcat:<bot_qq>:group:<group_qq>
```

QQ 昵称、群名片和 OneBot 发送者 `role` 永远不能建立 LivingAgent 权限。若要把配置的所有者绑定到 QQ 账户，请使用完整操作者 ID，例如：

```bash
export LIVING_AGENT_OWNER_ID='napcat:123456789:qq:987654321'
```

WebSocket 令牌认证 NapCat 适配器连接。`X-Self-ID` 提供机器人命名空间，但不是独立凭据；同时服务多个互不信任 NapCat 实例的部署应使用独立 LivingAgent 实例，或带认证的反向代理。

## 出站安全

适配器不能发送任意模型动作。每条用户可见运行时回复都会由宿主创建一个临时授权，绑定到：

- 操作者 `living-agent`；
- 能力 `platform.napcat.message`；
- 操作 `reply`；
- 确切会话和来源 TrustedEvent；
- 仅使用一次。

能力代理在适配器发送前验证类型化目标和消息参数。普通成员不能使用 `reply`；带危险污染的输入也不能授权写操作。出站模型文本编码为 OneBot `text` 段，因此形似 CQ 码的文本不能变成点名、图片、文件或其他富操作。NapCat 响应文字视为不可信传输数据，既不送入提示词也不记录；审计只保留有界状态字段。

第一个语言单元不等待节奏延迟。后续单元使用 `LIVING_AGENT_SOCIAL_FOLLOWUP_DELAY_MIN_MS` 与 `LIVING_AGENT_SOCIAL_FOLLOWUP_DELAY_MAX_MS` 的确定性中点。新输入会立即取消等待，让新的运行时轮次替换旧计划，而不是恢复旧计划。测试中设置 `LIVING_AGENT_TEST_DISABLE_DELAYS=true` 可取消等待。

## 当前限制

- 只支持反向 WebSocket；尚未实现正向 WebSocket、HTTP API 和 HTTP Webhook。
- 只有私聊/群聊消息事件属于认知输入；通知和请求事件会被忽略并审计。
- 回复仅支持纯文本。图片、文件、语音、引用回复、反应、群管理和 NapCat 扩展 API 均未开放。
- 没有主动或定时消息 API。
- OneBot `message_id` 重放去重尚未持久化，上游重放的重复事件可能产生重复回复。
- 在线 NapCat/QQ 账户属于外部基础设施，不在自动测试环境中。

## 参考资料

- [NapCat WebSocket 文档](https://napneko-napcatqq.mintlify.app/api/network/websocket)
- [NapCat HTTP API 文档](https://napneko-napcatqq.mintlify.app/api/network/http)
- [OneBot 11 WebSocket 协议](https://github.com/botuniverse/onebot-11/blob/master/communication/ws.md)
- [OneBot 11 消息事件](https://github.com/botuniverse/onebot-11/blob/master/event/message.md)

这些文档只用于查阅协议行为。LivingAgent 不依赖 NapCat Python/Node 包，核心运行时也不会导入 NapCat。
