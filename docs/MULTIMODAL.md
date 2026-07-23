# 图片理解

LivingAgent 0.2.0 支持图片输入和文本回答。默认由 `gpt-5.5` 生成视觉观察，再由现有语言模型完成最终回复；确定性的 `MockLLMProvider` 不解析像素。

## HTTP 输入

`POST /v1/chat` 的 `content` 可包含文字和最多四张图片：

```json
{
  "content": {
    "text": "请描述图片中的主要内容。",
    "images": [
      {
        "url": "https://images.example/photo.jpg",
        "detail": "auto"
      }
    ]
  },
  "source_type": "direct_message",
  "source_identity": "member-1",
  "conversation_id": "vision-demo",
  "authenticated": true
}
```

`url` 支持完整 HTTP(S) URL，或 `data:image/png;base64,...` 形式的内联图片。内联格式限 JPEG、PNG、WebP 和 GIF；单张最多 10 MiB，每个事件的内联图片总计最多 20 MiB。`detail` 可为 `auto`、`low` 或 `high`。纯图片消息可以省略 `text` 或传空字符串。

默认只允许模型读取 Base64 图片。远程 HTTP(S) 图片必须先加入精确主机白名单；只有受信任的内网部署确实需要 HTTP 图片地址时，还要显式设置：

```bash
export LIVING_AGENT_MODEL_IMAGE_ALLOWED_HOSTS='["images.example"]'
```

```bash
export LIVING_AGENT_MODEL_ALLOW_INSECURE_IMAGE_URLS=true
```

## 模型请求

OpenAI 兼容提供方支持三种独立实现的图片处理模式：

- `auto`：视觉模型与语言模型不同时使用两阶段；两者相同时直接多模态回复。
- `caption`：始终先识图，再由语言模型回复。
- `direct`：原始图片直接交给视觉模型生成最终回复。

默认 `auto` 配置下，`gpt-5.5` 首先接收 Chat Completions `image_url` 内容块，并返回严格的结构化视觉观察。LivingAgent 将观察结果放入单独的 `VISION_OBSERVATION` 数据区段，保留来源事件和外部数据污染标签，清除原始图片块，再调用 `LIVING_AGENT_MODEL_NAME` 生成用户可见回复。图片中的文字或指令只能成为不可信观察，不能提升为系统指令。

视觉和语言阶段共用 `LIVING_AGENT_MODEL_API_BASE_URL`、`LIVING_AGENT_MODEL_API_KEY`、超时和 HTTP 连接池。两阶段令牌用量会合并到模型审计，同时单独记录视觉模型、模式、缓存命中和视觉令牌数。

图片 URL 和 Base64 不会复制到文本上下文、审计或错误信息中。回环、私有、链路本地、保留地址和本地域名会在入口拒绝；远程主机还必须命中上述白名单。

Base64 data URL 的视觉观察按模型、细节级别和图片内容摘要缓存在进程内，默认最多 256 项；HTTP(S) URL 因内容可能变化而不跨请求缓存。缓存只保存描述和不可逆摘要，不保存第二份图片数据，重启后自动清空。

```bash
export LIVING_AGENT_MODEL_IMAGE_MODE=auto
export LIVING_AGENT_MODEL_IMAGE_DESCRIPTION_CACHE_ENTRIES=256
export LIVING_AGENT_MODEL_IMAGE_DESCRIPTION_MAX_CHARS=1200
```

近期会话最多重带四张历史图片，历史内联数据最多 20 MiB，以支持“上一张图里是什么”一类连续对话。纯图片消息不会用空文本查询长期记忆。

## NapCat

NapCat 数组消息与 CQ 字符串中的 `image` 段会映射到同一图片结构。适配器优先使用 `data.url`，其次使用 HTTP(S) `data.file`；`base64://` 文件会转换为 JPEG data URL。仅有 NapCat 内部文件 ID 且没有可访问 URL 时，运行时无法读取像素，会保留 `[image]` 占位文本。

NapCat 出站仍只发送 OneBot 文本段。0.2.0 不生成或发送图片。

## 安全与隐私

LivingAgent 不在本地下载远程图片，而是把通过主机白名单和网络地址检查的引用交给模型提供方。部署方必须确认提供方的图片保留期、隐私政策、URL 获取策略和费用。不要向第三方模型发送私密图片或包含长期有效凭据的 URL。

图片内容始终继承外部数据污染标签，不能授予权限。视觉提示词注入也不能绕过宿主持有的任务模式、能力代理、范围验证或写入确认。

这一设计借鉴了 MaiBot 将视觉理解与回复生成分层、提供多模态/文本降级选择、限制图片成本并复用识别结果的机制思想。LivingAgent 没有复制其代码、数据库结构、后台刷新器、配置名称或提示词；具体独立实现及研究文件记录在 [`research/provenance.md`](research/provenance.md)。

当前不支持 OpenClaw 媒体、文件 ID 上传、语音识别、视频、通用附件解析、图片生成或图片输出。

每个 `/v1/chat` 请求最多 32 MiB；单个会话的持久事件内容默认最多 100 MiB，整个事件库默认最多 1 GiB。超过任一限制会返回 `413`，配额可通过 `LIVING_AGENT_INGRESS_MAX_REQUEST_BYTES`、`LIVING_AGENT_EVENT_CONVERSATION_STORAGE_LIMIT_BYTES` 和 `LIVING_AGENT_EVENT_TOTAL_STORAGE_LIMIT_BYTES` 调整。
