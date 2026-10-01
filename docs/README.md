# 开发者文档 / Developer Documentation

本索引为 LivingAgent 的全部仓库文档提供中英文入口。文档正文以中文记录实现细节，英文说明概括每份文档的用途与边界；根目录另有完整英文入口 [`README.en.md`](../README.en.md)。API 路径、环境变量、模型名和代码标识符保持英文原文。

This index provides bilingual access to all repository documentation. The document bodies preserve the detailed Chinese implementation record, while the English descriptions below explain each document's purpose and scope. A complete English project entry point is available in [`README.en.md`](../README.en.md). API paths, environment variables, model names, and code identifiers are intentionally not translated.

## 架构与安全 / Architecture and security

- [`REFACTOR_VALIDATION.md`](REFACTOR_VALIDATION.md) — Agent 重构验收记录与环境边界。 / Agent refactor validation and environment limits.
- [`AGENT_RUNTIME.md`](AGENT_RUNTIME.md) — 人格社交与持久目标闭环、工具目录、恢复和控制台。 / Persona, persistent goal loops, tools, recovery and console.

- [`ASSUMPTIONS.md`](ASSUMPTIONS.md) — 工程、运行环境和信任假设。 / Engineering, runtime, and trust assumptions.
- [`PROJECT_PLAN.md`](PROJECT_PLAN.md) — 架构目标、阶段状态和交付标准。 / Architecture goals, phase status, and delivery criteria.
- [`THREAT_MODEL.md`](THREAT_MODEL.md) — 资产、信任边界、注入与供应链威胁。 / Assets, trust boundaries, injection risks, and supply-chain threats.
- [`SECURITY_HARDENING.md`](SECURITY_HARDENING.md) — 管理认证、沙箱、确认式 Shell 和幂等加固。 / Management authentication, sandboxing, confirmation-gated shell, and idempotency hardening.
- [`adr/0001-greenfield-runtime.md`](adr/0001-greenfield-runtime.md) — 从零构建独立运行时的决策。 / Decision to build an independent greenfield runtime.
- [`adr/0002-policy-outside-model.md`](adr/0002-policy-outside-model.md) — 将策略与实际影响置于模型之外。 / Decision to keep policy and side effects outside the model.

## 功能与集成 / Features and integrations

- [`MULTIMODAL.md`](MULTIMODAL.md) — 图片输入、模型请求、NapCat 映射及隐私边界。 / Image input, model requests, NapCat mapping, and privacy boundaries.
- [`integrations/cloud-model-api.md`](integrations/cloud-model-api.md) — OpenAI 兼容聊天模型配置、重试与静默失败。 / OpenAI-compatible chat-model configuration, retries, and silent terminal failures.
- [`integrations/embeddings.md`](integrations/embeddings.md) — 嵌入提供方、API、持久索引与混合召回。 / Embedding providers, APIs, persistent indexing, and hybrid retrieval.
- [`integrations/napcat.md`](integrations/napcat.md) — OneBot 11 反向 WebSocket、身份映射、队列与发送安全。 / OneBot 11 reverse WebSocket, identity mapping, queueing, and send safety.
- [`integrations/openclaw-wechat.md`](integrations/openclaw-wechat.md) — OpenClaw 微信桥接、严格模式和回执合同。 / OpenClaw WeChat bridge, strict mode, and delivery-receipt contract.

## 阶段记录 / Phase records

- [`PHASE_1.md`](PHASE_1.md) — 可信事件与安全运行管线。 / Trusted events and the secure runtime pipeline.
- [`PHASE_2.md`](PHASE_2.md) — 隔离计算器插件垂直切片。 / Isolated calculator-plugin vertical slice.
- [`PHASE_3.md`](PHASE_3.md) — 记忆、人格和提示词管理。 / Memory, persona, and prompt management.
- [`PHASE_4.md`](PHASE_4.md) — 持久心理状态与连续性证据。 / Persistent psyche state and continuity evidence.
- [`PHASE_5.md`](PHASE_5.md) — 仿生发言、会话动量和中断。 / Biomimetic utterances, conversation momentum, and interruption.
- [`PHASE_6.md`](PHASE_6.md) — 持久任务合同、执行和证据。 / Persistent task contracts, execution, and evidence.
- [`PHASE_7.md`](PHASE_7.md) — 管理控制台与安全边界。 / Management console and its security boundaries.
- [`PHASE_8.md`](PHASE_8.md) — 日常、日记、睡眠和梦境隔离。 / Daily life, diary, sleep, and dream isolation.

## 版本说明 / Release notes

- [`RELEASE_0.3.0.md`](RELEASE_0.3.0.md) — 持久 Agent、人格式结果呈现、运行时拆分和断路修复。 / Persistent agents, persona outcome presentation, runtime separation, and functional repairs.
- [`RELEASE_0.2.1.md`](RELEASE_0.2.1.md) — 社交运行时。 / Social runtime.
- [`RELEASE_0.2.2.md`](RELEASE_0.2.2.md) — 自动记忆与平台可靠性。 / Automatic memory and platform reliability.
- [`RELEASE_0.2.3.md`](RELEASE_0.2.3.md) — 受控工作能力。 / Controlled work capabilities.
- [`RELEASE_0.2.4.md`](RELEASE_0.2.4.md) — 可信用户工作、确认式 Shell 与记忆生命周期。 / Trusted-user work, confirmation-gated shell, and memory lifecycle.
- [`RELEASE_0.2.6.md`](RELEASE_0.2.6.md) — 可安装资产、NapCat 队列、模型恢复和控制台认证。 / Installable assets, NapCat queueing, model recovery, and console authentication.

## 研究来源 / Research provenance

- [`research/maibot-mechanisms.md`](research/maibot-mechanisms.md) — 值得研究的 MaiBot 机制。 / MaiBot mechanisms worth studying.
- [`research/maibot-limitations.md`](research/maibot-limitations.md) — 不能直接采用 MaiBot 架构的原因。 / Why MaiBot's architecture cannot be adopted directly.
- [`research/provenance.md`](research/provenance.md) — 精确修订、查阅文件和借用声明。 / Exact revision, inspected files, and borrowing declaration.
