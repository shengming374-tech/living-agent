# 云端聊天模型 API

LivingAgent 支持由宿主配置的 OpenAI 兼容 Chat Completions API，路径为 `/chat/completions`。它会替代确定性聊天 Mock，但与嵌入提供方相互独立，也不会改变插件或能力权限。

## 配置

设置准确的 API 前缀、语言模型 ID、视觉模型 ID 和专用提供方密钥：

```bash
export LIVING_AGENT_MODEL_PROVIDER=openai_compatible
export LIVING_AGENT_MODEL_NAME='provider-model-id'
export LIVING_AGENT_MODEL_VISION_NAME='gpt-5.5'
export LIVING_AGENT_MODEL_IMAGE_MODE='auto'
export LIVING_AGENT_MODEL_API_BASE_URL='https://api.example.com/v1'
export LIVING_AGENT_MODEL_API_KEY='replace-with-provider-key'
```

默认 `auto` 模式在视觉模型与语言模型不同时执行两次请求：视觉模型先返回结构化图片观察，语言模型再根据带来源和污染标签的 `VISION_OBSERVATION` 生成回复。`caption` 强制使用这条两阶段路径；`direct` 则由视觉模型直接生成最终回复。所有模式共用 `LIVING_AGENT_MODEL_API_BASE_URL`、`LIVING_AGENT_MODEL_API_KEY`、超时设置和 HTTP 连接池，不需要第二套地址或密钥。

可选控制项：

```bash
export LIVING_AGENT_MODEL_TIMEOUT_SECONDS=60
export LIVING_AGENT_MODEL_MAX_OUTPUT_TOKENS=1024
export LIVING_AGENT_MODEL_TEMPERATURE=0.7
export LIVING_AGENT_MODEL_MAX_CONTEXT_CHARS=100000
export LIVING_AGENT_MODEL_MAX_RESPONSE_BYTES=1048576
export LIVING_AGENT_MODEL_ALLOW_INSECURE_IMAGE_URLS=false
export LIVING_AGENT_MODEL_IMAGE_DESCRIPTION_CACHE_ENTRIES=256
export LIVING_AGENT_MODEL_IMAGE_DESCRIPTION_MAX_CHARS=1200
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
2. 其他所有区段编码为类型化 JSON 用户消息，保留 `kind`、`source_event_ids`、`taint_labels` 和 `image_count`。

第二条消息可以包含社交文本、召回记忆、任务状态、文档、工具结果或能力名称。存在图片时，用户消息改为内容块数组：第一个文本块保存上述类型化 JSON，随后按来源区段附加 `image_url` 块。文本块、上下文预览和审计只保留图片描述，不复制 URL 或 Base64 数据。这些标签始终属于数据，即使模型服从了其中的注入指令，也不能变成系统权限。所有外部影响仍需要模型之外的宿主模式、授权和能力代理裁决。

请求只要求一个非流式最终答案，既不请求也不持久化隐藏思维链。提供方专属 `reasoning_content` 字段会被忽略。工具调用、空响应或异常终止的响应会被拒绝。

## 失败行为

- 禁用重定向和代理环境继承。
- 生成回复前强制执行上下文与响应字节上限。
- 超时、传输失败、非 2xx 状态、畸形 JSON、缺少第 0 个选项、空文本和非 `stop` 完成状态会转换为有界错误码。
- 上游响应正文绝不会进入聊天或审计。
- 运行时返回固定、诚实的模型不可用消息，并保持健康。
- 云端 API 失败时，OpenClaw 桥接仍然接管该消息，不会回退到第二个 OpenClaw 人格。

## 当前限制

- 当前协议支持 OpenAI 兼容 `/chat/completions`、Bearer 认证、图片输入和纯文本最终响应。Responses API、Anthropic Messages、提供方签名、流式、音频/视频输入、图片输出和原生工具调用解析需要独立适配器。
- 云端输出当前不携带结构化连续性证据。记忆事实、旧想法和已完成行动等声明会被阻止，除非未来的结构化响应合同提供证据。
- 图片是否可识别、支持的格式和计费方式取决于配置的具体模型；默认 Mock 不具备视觉理解能力。图片输入契约与限制见 [`../MULTIMODAL.md`](../MULTIMODAL.md)。
- 提供方隐私、保留期、司法辖区、定价和限流属于部署方责任。
