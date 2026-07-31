# OpenClaw 微信集成 / OpenClaw WeChat Integration

LivingAgent 可以把 OpenClaw 的 `openclaw-weixin` 通道用作传输层。内置 OpenClaw 插件通过类型化 `before_dispatch` Hook 接管选定入站消息，向 LivingAgent 发送严格请求，再把 LivingAgent 响应作为 OpenClaw 合成回复返回。

OpenClaw 负责微信登录、轮询和最终消息投递。它不是人格前端、模型提供方、任务规划器、权限裁决者或记忆系统。被接管消息不会运行 OpenClaw Agent。

```text
微信
  -> @tencent-weixin/openclaw-weixin
  -> OpenClaw before_dispatch
  -> living-agent-bridge（Bearer 认证 HTTP）
  -> LivingAgent TrustedEvent / 认知 / 能力代理
  -> 合成回复
  -> OpenClaw 通道投递
  -> 微信
```

## 已支持的垂直切片

- 配置的 `openclaw-weixin` 账户收到的私聊与群聊文本消息。
- 群聊提及元数据进入既有发言判断；明确提及会触发，未提及消息默认只观察。
- 桥接两端都使用精确通道和可选账户白名单。
- 稳定、带平台命名空间的用户和会话身份。
- 持久化请求指纹去重和消息 ID 冲突检测。
- 持久化进行中回复 Session 和幂等投递进度。
- 对确切来源事件回复的单次代理授权。
- 失败关闭的 OpenClaw 行为：桥接错误记录为有界错误码，不回退到其他 OpenClaw 人格。
- 需要 `operator.read` 的只读 `livingAgentBridge.status` Gateway RPC。

本切片刻意不实现附件、富回复和主动发送。

## LivingAgent 配置

生成专用高熵令牌，不要复用 OpenClaw Gateway 令牌。

```bash
export LIVING_AGENT_OPENCLAW_BRIDGE_ENABLED=true
export LIVING_AGENT_OPENCLAW_BRIDGE_ACCESS_TOKEN='replace-with-a-long-random-token'
export LIVING_AGENT_OPENCLAW_BRIDGE_ALLOWED_CHANNELS='["openclaw-weixin"]'
export LIVING_AGENT_OPENCLAW_BRIDGE_ALLOWED_ACCOUNT_IDS='["your-weixin-account-id"]'
uv run uvicorn --app-dir src living_agent.app:app --host 127.0.0.1 --port 8765
```

桥接端点：

```text
POST http://127.0.0.1:8765/v1/adapters/openclaw/messages
Authorization: Bearer <专用桥接令牌>
```

启用适配器却没有非空令牌时，启动验证失败。以上默认 HTTP 绑定只监听回环地址。

## 安装 OpenClaw 插件

以开发链接方式安装仓库插件：

```bash
openclaw plugins install --link ./integrations/openclaw/living-agent-bridge
```

通过 OpenClaw 界面或配置工具设置 `plugins.entries.living-agent-bridge.config`：

```json
{
  "endpoint": "http://127.0.0.1:8765/v1/adapters/openclaw/messages",
  "token": "replace-with-the-same-dedicated-token",
  "channelId": "openclaw-weixin",
  "allowedAccountIds": ["your-weixin-account-id"],
  "timeoutMs": 90000,
  "followupDelayMs": 450,
  "maxMessageChars": 12000,
  "allowRemoteEndpoint": false
}
```

`followupDelayMs` 是兼容后备值。当前 LivingAgent 响应会携带从运行时发言配置派生并经过验证的逐单元延迟元数据；桥接按该数据累计安排后续消息。

同一会话收到新输入时，桥接取消旧响应中仍在等待的后续单元；旧模型响应若在新输入之后才完成，也会被压制。插件会为采用的首单元，以及每个后续 `sendText` 成功事件提交认证投递回执。LivingAgent 只把对应单元记录为已说出。被新输入替代 Session 的回执会被拒绝，不能进入会话历史。

LivingAgent 持久化 Session 单元、精确传输范围、代次和投递数量。重启后被动恢复当前 Session，但不会自行重发旧内容。桥接可以按顺序继续提交认证回执；重复回执返回 `delivery_already_recorded`，跳过索引会失败关闭，任何新输入都会永久作废旧计划剩余部分。

修改插件配置后重启 Gateway：

```bash
openclaw gateway restart
openclaw plugins info living-agent-bridge --json
openclaw channels status --json
```

插件状态必须为 `loaded`，选定 `openclaw-weixin` 账户必须已启用、配置并运行。若旧桥接也接管同一通道，应先禁用旧桥接。不要配置回退到 OpenClaw Agent，否则同一会话会暴露两个不同人格。

状态 RPC 只用于可选诊断：

```bash
openclaw gateway call livingAgentBridge.status --json
```

OpenClaw 可能要求本地 CLI 设备已配对，或获批 `operator.read` 范围。应通过正常 OpenClaw 设备流程批准，不能为了诊断调用而削弱 Gateway 认证。

## 身份与信任映射

桥接创建稳定命名空间：

```text
操作者:  openclaw:<channel>:<account>:user:<sender>
私聊:    openclaw:<channel>:<account>:direct:<conversation>
群聊:    openclaw:<channel>:<account>:group:<conversation>
```

OpenClaw 2026.6.10 的类型化 `before_dispatch` 合同不保证通道把旧 `From`/`To` 值映射到 `senderId` 和 `conversationId`。私聊中二者都不存在时，桥接会根据认证通道、账户和 OpenClaw Session 键派生稳定不透明 `session-<sha256>` 身份；原始 Session 键和微信 ID 不进入该身份。既没有显式 ID，也没有稳定 Session 键时，消息失败关闭。群聊依赖 Hook 提供 `isGroup` 以及 `wasMentioned` 或 `mentionsAgent` 信号；缺失提及信号时按未提及群消息处理，不会扩大回复权限。

共享令牌认证已安装桥接进程，通道和账户白名单限制其范围。`senderId`、`conversationId` 和账户元数据由认证 OpenClaw 通道提供。展示名和消息内容永远不能授予所有者或管理员权限。只有单独验证平台账户后，才能把所有者绑定到完整命名空间操作者 ID。

## 安全行为

每条响应都会由宿主为操作者 `living-agent`、能力 `platform.openclaw.message`、操作 `reply` 和确切会话/来源事件创建临时授权。能力代理验证类型化回复后，OpenClaw 才能收到。外部消息污染标签在运行时传播，疑似注入指令不能变成权限或能力授权。

OpenClaw 插件不注册工具、模型提供方、通道、后台服务或执行能力。它只发送最小消息元数据，永远拿不到 Agent 对象、数据库、长期记忆、人格、提示词或插件注册表。错误会压缩为有界错误码，防止响应正文和本地秘密进入通道消息。

默认拒绝远端端点。显式启用时也只接受 HTTPS；生产使用还需要服务器认证、秘密轮换、请求限流和符合威胁模型的网络边界。

## 当前限制

- 只接受文本消息；群聊需要通道提供稳定会话和发送者身份，缺失提及元数据时只按未提及消息处理。
- 首个响应是一个合成文本载荷；附件和平台操作不可用。
- 入站消息 ID 指纹和终止重放响应已经持久化。先前调用被中断后的重试会失败关闭，不重新进入运行时；发送方可使用新的平台消息 ID 显式重试。
- 后备消息 ID 是确定性哈希，因为当前 `before_dispatch` 合同没有暴露原生消息 ID。
- 可自动检查 OpenClaw 插件启用和通道健康，但真实微信往返需要已登录账户和外部发送者。
- 共享 Bearer 令牌认证桥接，但不是进程证明。两个服务都应位于回环地址或受保护网络。

## 协议参考

- [OpenClaw 插件 Hook](https://docs.openclaw.ai/plugins/hooks)
- [OpenClaw 通道出站 SDK](https://docs.openclaw.ai/plugins/sdk-channel-outbound)
- [OpenClaw 微信通道](https://documentation.openclaw.ai/channels/wechat)
- [OpenClaw Gateway 协议](https://docs.openclaw.ai/gateway/protocol)

这些参考只定义传输行为。OpenClaw 是可选外部平台传输，不是 LivingAgent 运行时依赖。本集成不使用 MCP。
