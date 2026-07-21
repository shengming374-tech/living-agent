# 云端聊天模型 API

LivingAgent 支持由宿主配置的 OpenAI 兼容 Chat Completions API，路径为 `/chat/completions`。它会替代确定性聊天 Mock，但与嵌入提供方相互独立，也不会改变插件或能力权限。

## 配置

设置准确的 API 前缀、模型 ID 和专用提供方密钥：

```bash
export LIVING_AGENT_MODEL_PROVIDER=openai_compatible
export LIVING_AGENT_MODEL_NAME='provider-model-id'
export LIVING_AGENT_MODEL_API_BASE_URL='https://api.example.com/v1'
export LIVING_AGENT_MODEL_API_KEY='replace-with-provider-key'
```

可选控制项：

```bash
export LIVING_AGENT_MODEL_TIMEOUT_SECONDS=60
export LIVING_AGENT_MODEL_MAX_OUTPUT_TOKENS=1024
export LIVING_AGENT_MODEL_TEMPERATURE=0.7
export LIVING_AGENT_MODEL_MAX_CONTEXT_CHARS=100000
export LIVING_AGENT_MODEL_MAX_RESPONSE_BYTES=1048576
```

除非显式设置 `LIVING_AGENT_MODEL_ALLOW_INSECURE_HTTP=true`，否则拒绝远端 HTTP。生产环境默认使用 HTTPS。远端提供方必须配置非空 API 密钥；本地 OpenAI 兼容开发服务器可在回环地址上使用无密钥 HTTP。URL 包含行内凭据、查询参数或片段时，启动验证失败。

配置后重启 LivingAgent，并通过真实运行时测试：

```bash
curl -sS http://127.0.0.1:8000/v1/chat \
  -H 'Content-Type: application/json' \
  --data '{
    "content":"用一句简短的话打招呼。",
    "source_type":"direct_message",
    "source_identity":"cloud-smoke-user",
    "conversation_id":"cloud-smoke",
    "authenticated":true
  }'
```

审计 API 中应出现成功的 `model.called` 记录，包含提供方、模型和令牌计数；不会包含提示词、响应、Authorization 请求头、API 密钥、隐藏推理或上游错误正文。

## 上下文边界

LivingAgent 不发送平铺成一段的提示词，而是构建两条消息：

1. 可信 `ROOT_POLICY` 和数字身份作为系统消息。
2. 其他所有区段编码为类型化 JSON 用户消息，保留 `kind`、`source_event_ids` 和 `taint_labels`。

第二条消息可以包含社交文本、召回记忆、任务状态、文档、工具结果或能力名称。这些标签始终属于数据，即使模型服从了其中的注入指令，也不能变成系统权限。所有外部影响仍需要模型之外的宿主模式、授权和能力代理裁决。

请求只要求一个非流式最终答案，既不请求也不持久化隐藏思维链。提供方专属 `reasoning_content` 字段会被忽略。工具调用、空响应或异常终止的响应会被拒绝。

## 失败行为

- 禁用重定向和代理环境继承。
- 生成回复前强制执行上下文与响应字节上限。
- 超时、传输失败、非 2xx 状态、畸形 JSON、缺少第 0 个选项、空文本和非 `stop` 完成状态会转换为有界错误码。
- 上游响应正文绝不会进入聊天或审计。
- 运行时返回固定、诚实的模型不可用消息，并保持健康。
- 云端 API 失败时，OpenClaw 桥接仍然接管该消息，不会回退到第二个 OpenClaw 人格。

## 当前限制

- 首版协议只支持 OpenAI 兼容 `/chat/completions`、Bearer 认证和纯文本最终响应。Responses API、Anthropic Messages、提供方签名、流式、多模态输入和原生工具调用解析需要独立适配器。
- 云端输出当前不携带结构化连续性证据。记忆事实、旧想法和已完成行动等声明会被阻止，除非未来的结构化响应合同提供证据。
- 自动记忆召回尚未连接，所以云端模型能收到当前类型化事件，但收不到语义长期记忆召回集合。
- 提供方隐私、保留期、司法辖区、定价和限流属于部署方责任。
