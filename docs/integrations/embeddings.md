# 嵌入模型与 API 集成 / Embedding Model and API Integration

LivingAgent 具有宿主持有的嵌入提供方边界，包含两个实现：

- `mock`：面向测试和本地开发的确定性归一化特征哈希；
- `openai_compatible`：调用 OpenAI 兼容 `/embeddings` API 的 HTTP 客户端。

显式嵌入 API 只向所有者开放。可选的记忆索引由宿主服务持有，不向 LLM、插件或普通聊天用户暴露。

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

记忆索引状态与重建：

```bash
curl -sS http://127.0.0.1:8000/v1/memories/embedding-status \
  -H 'X-Actor-ID: owner-local' \
  -H 'Authorization: Bearer <management-token>'

curl -sS -X POST http://127.0.0.1:8000/v1/memories/reindex \
  -H 'X-Actor-ID: owner-local' \
  -H 'Authorization: Bearer <management-token>'
```

启用保守候选提取和本地记忆向量：

```bash
export LIVING_AGENT_MEMORY_AUTO_CANDIDATES_ENABLED=true
export LIVING_AGENT_MEMORY_EMBEDDINGS_ENABLED=true
export LIVING_AGENT_MEMORY_EMBEDDINGS_ALLOW_REMOTE=false
```

回环地址会识别为本地。若 API 位于真正远端，必须额外设置 `LIVING_AGENT_MEMORY_EMBEDDINGS_ALLOW_REMOTE=true`；这表示部署所有者明确同意向该提供方发送已提交现实记忆和用户召回查询。

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

自动记忆索引使用单独的 `embed` 操作。宿主配置启用后，每个批次仍创建精确单次授权，携带来源事件 ID 和污染标签。危险污染会被代码策略拒绝；不产生伪造的逐次“用户确认”审计。

## 记忆索引与召回

- 只索引已提交、启用且事实性为 `verified`、`reported` 或 `inferred` 的记忆。
- 向量记录绑定记忆版本、内容校验、提供方、模型和维度。
- 内容或主题变化会重建向量；只有置信度等元数据变化时复用向量并推进版本。
- 删除、梦境、想象和虚构记忆不会保留在现实索引。
- 启动时对缺失或过期向量执行有界回填；提供方失败不会阻止运行时启动。
- 召回先过滤稳定私人身份和精确会话范围，再混合语义、词法、重要度和置信度排序。
- 提供方或索引失败时自动降级到词法召回。

输入文本、向量、API 密钥、Authorization 请求头和上游错误正文都不会写入审计。提供方客户端禁用重定向和代理环境继承。非成功响应正文不会通过 LivingAgent API 暴露。

## 当前限制

- 远端协议只支持 OpenAI 兼容 Bearer 认证。提供方专属签名和非标准请求格式需要独立适配器。
- 状态端点只报告配置和限制，不会发起付费提供方请求。
- 自动候选是有限规则提取，不是 LLM 开放式抽取；默认自动审批只处理提取器新建且通过记忆防火墙的候选，手工候选仍需所有者提交，两个自动开关都可由部署配置关闭。
- 当前向量以 JSON 持久化并在应用进程中计算余弦相似度；大规模数据和 PostgreSQL 部署仍需要 `pgvector` 或等价索引。
- 模型切换会把旧向量标为过期并在启动或手动重建时刷新，不提供双模型在线迁移。
- Mock 提供方只是确定性测试基础设施，不是语义模型。

这些限制保证未来执行排序或外部处理前，私人或跨会话记忆仍会先经过范围过滤。

## 验证

- 完整 Python 测试：212 项通过。
- 记忆候选、向量生命周期、范围隔离、污染拒绝、远端许可、降级和回填专项测试：12 项通过。
- Ruff 与严格 mypy：通过。
- OpenClaw 桥接回归：13 项通过。
- 使用 LM Studio `text-embedding-qwen3-embedding-0.6b` 的 1024 维真实冒烟通过：不同措辞的查询成功召回已提交私人记忆。
