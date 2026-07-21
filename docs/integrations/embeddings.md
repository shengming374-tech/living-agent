# 嵌入模型与 API 集成

LivingAgent 具有宿主持有的嵌入提供方边界，包含两个实现：

- `mock`：面向测试和本地开发的确定性归一化特征哈希；
- `openai_compatible`：调用 OpenAI 兼容 `/embeddings` API 的 HTTP 客户端。

嵌入 API 是显式的所有者控制面操作，不向 LLM、插件、普通聊天用户或自动记忆接入开放。

## 配置 OpenAI 兼容提供方

设置提供方、API 前缀和准确模型名称：

```bash
export LIVING_AGENT_EMBEDDING_PROVIDER=openai_compatible
export LIVING_AGENT_EMBEDDING_MODEL='your-embedding-model'
export LIVING_AGENT_EMBEDDING_API_BASE_URL='https://api.example.com/v1'
export LIVING_AGENT_EMBEDDING_API_KEY='replace-with-provider-key'
```

如果模型允许选择输出宽度，请显式配置：

```bash
export LIVING_AGENT_EMBEDDING_DIMENSIONS=1536
```

配置维度后，任何不同宽度的响应都会被拒绝。省略时由提供方响应决定宽度，但同一批次所有向量仍必须等宽。

本地 OpenAI 兼容服务器可使用回环 HTTP：

```bash
export LIVING_AGENT_EMBEDDING_API_BASE_URL='http://127.0.0.1:11434/v1'
```

除非显式设置 `LIVING_AGENT_EMBEDDING_ALLOW_INSECURE_HTTP=true`，否则拒绝远端明文 HTTP。远端仍推荐 HTTPS。URL 包含凭据、查询参数或片段时，启动验证失败。

可用限制：

```bash
export LIVING_AGENT_EMBEDDING_TIMEOUT_SECONDS=15
export LIVING_AGENT_EMBEDDING_MAX_BATCH_SIZE=32
export LIVING_AGENT_EMBEDDING_MAX_INPUT_CHARS=12000
export LIVING_AGENT_EMBEDDING_MAX_TOTAL_CHARS=48000
export LIVING_AGENT_EMBEDDING_MAX_RESPONSE_BYTES=4194304
```

## LivingAgent API

开发 API 使用配置的所有者身份：

```bash
curl -sS http://127.0.0.1:8000/v1/embeddings/status \
  -H 'X-Actor-ID: owner-local' \
  -H 'Authorization: Bearer <management-token>'

curl -sS http://127.0.0.1:8000/v1/embeddings \
  -H 'X-Actor-ID: owner-local' \
  -H 'Authorization: Bearer <management-token>' \
  -H 'Content-Type: application/json' \
  --data '{"input":["第一段文本","第二段文本"]}'
```

`POST /v1/embeddings` 返回与 OpenAI 形状一致的有序向量列表，并附带配置的提供方名称和验证后维度。请求不能覆盖已配置模型；未知字段和空输入会被拒绝。

`X-Actor-ID` 只用于选择稳定身份。生产设置要求先通过独立管理 Bearer 令牌才能访问这些端点。反向代理或外部身份提供方可以增加更强的操作者认证。

## 权限与数据边界

嵌入被归类为外部数据传输。每个请求中，宿主代码会：

1. 验证所有者权限；
2. 应用批次、单输入、总字符和响应字节限制；
3. 为 `model.embedding.generate` / `send` 创建一个临时授权；
4. 请求能力代理验证并消耗这个精确授权；
5. 只有所有者确认后才发送批次；
6. 验证 HTTP 状态、JSON 形状、索引、有限浮点数和维度；
7. 审计提供方、模型、数量、总字符、维度或有界错误码。

输入文本、向量、API 密钥、Authorization 请求头和上游错误正文都不会写入审计。提供方客户端禁用重定向和代理环境继承。非成功响应正文不会通过 LivingAgent API 暴露。

## 当前限制

- 远端协议只支持 OpenAI 兼容 Bearer 认证。提供方专属签名和非标准请求格式需要独立适配器。
- 状态端点只报告配置和限制，不会发起付费提供方请求。
- 嵌入向量会返回给所有者，但尚未持久化。
- 已提交记忆不会自动发送给嵌入提供方。
- 语义/向量记忆召回、索引重建、模型迁移和 PostgreSQL 向量加速尚未实现。
- Mock 提供方只是确定性测试基础设施，不是语义模型。

这些限制保证未来执行排序或外部处理前，私人或跨会话记忆仍会先经过范围过滤。
