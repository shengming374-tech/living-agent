# LivingAgent

[中文](README.md) | [English](README.en.md)

LivingAgent is a persistent digital-persona runtime designed from scratch for natural social participation and reliable, policy-constrained task execution. It does not claim consciousness and does not invent a biological body or real-life experiences.

The current release includes trusted input handling, capability-brokered execution, provenance-preserving long-term memory, managed persona and prompt versions, persistent psyche evidence, a multi-step execution kernel, image understanding, conversation scheduling, automatic memory proposals, controlled workspace and web tools, confirmation-gated shell execution, dual-layer factual and narrative memory, installable runtime assets, bounded NapCat event queues, transient model-failure recovery, and authenticated management-console loading.

Voice, video, generic attachment parsing, image generation, proactive messaging, arbitrary natural-language action planning, and third-party business connectors remain out of scope.

## Project goals / 项目目标

- Present one consistent persona while separating social cognition from execution cognition internally.
- Preserve event and context provenance instead of flattening all text into instructions.
- Enforce capability decisions in code, outside the language model.
- Keep tasks, evidence, memory provenance, and state changes auditable.
- Run native plugins with least privilege and isolation from the host runtime.

## Non-goals / 非目标

- Simulating a biological body or claiming real consciousness.
- Forking, wrapping, importing, or requiring MaiBot at runtime.
- Using MaiBot or MCP as the persona frontend or native plugin runtime.
- Arbitrary shell execution, self-approval, self-deployment, or security-policy changes through chat.

## Architecture / 架构

```text
Platform/API input
        |
        v
Trust boundary -> TrustedEvent -> participation decision
        |                                |
        |                         social cognition
        |                                |
        +-> typed context compiler <- structured execution result
                                               |
                                         behavior proposal
                                               |
                                          policy engine
                                               |
                                       capability broker
                                     / deny ask allow \
                                    v                v
                             host capability    plugin process
                                    \                /
                                      verified evidence
                                               |
                                       social cognition -> user

All decisions and side effects ---------------------> audit log
```

Execution cognition never sends natural-language messages directly. It returns structured results, and social cognition expresses them through the single persona.

The production authentication, plugin sandbox, and persistent ingress-idempotency controls are documented in [`docs/SECURITY_HARDENING.md`](docs/SECURITY_HARDENING.md).

## Development and startup / 开发与运行

Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) are recommended.

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run mypy
uv run uvicorn --app-dir src living_agent.app:app --reload
```

After startup, use `GET /health`, open `/studio`, or submit an authenticated adapter envelope to `POST /v1/chat`. Defaults live in `config/default.yaml`; deployment overrides are listed in `.env.example`.

When installed from a wheel, the default configuration, persona, prompts, and calculator plugin are copied to `LIVING_AGENT_RUNTIME_ROOT` (the current directory by default) on first startup. Migrations run directly from read-only package resources. Existing complete directories are never overwritten. A partially missing default directory or a missing explicitly configured path fails startup instead of mixing asset versions.

The read-only psyche CLI uses the same owner API:

```bash
uv run living-agent-psyche show
uv run living-agent-psyche watch --interval 1
```

Production deployments must set a dedicated `LIVING_AGENT_MANAGEMENT_API_TOKEN` of at least 32 characters. The browser keeps this token in `sessionStorage`, not persistent storage. A remote psyche URL must use HTTPS and an explicit `LIVING_AGENT_PSYCHE_TOKEN` or `--token`.

## Model configuration / 模型配置

The deterministic `MockLLMProvider` is the default and needs no credentials. The `openai_compatible` provider calls a host-configured `/chat/completions` endpoint.

Connection errors, timeouts, and HTTP 408, 429, 500, 502, 503, and 504 responses are attempted at most twice by default. Backoff is bounded by `LIVING_AGENT_MODEL_RETRY_BASE_SECONDS` and `LIVING_AGENT_MODEL_RETRY_MAX_SECONDS`; `Retry-After` is capped by the same maximum. Other HTTP, protocol, and content failures are not retried. If all attempts fail, social entry points remain silent and do not create or deliver an utterance; only a redacted error category is audited.

Images can be supplied to `POST /v1/chat` through `content.images`, with at most four HTTP(S) URLs or Base64 data URLs. Remote image hosts require an exact allowlist, and private or local addresses are rejected. See [`docs/MULTIMODAL.md`](docs/MULTIMODAL.md).

Embedding providers are configured independently. The OpenAI-compatible implementation validates response counts, indices, finite values, and dimensions. Sending memory text to a remote provider requires an exact one-shot capability grant. See [`docs/integrations/embeddings.md`](docs/integrations/embeddings.md).

Secrets belong only in supported environment variables. They must never enter prompts, previews, or audit content.

## Native plugins / 原生插件

The host discovers strict manifests and starts an isolated Python subprocess for each plugin invocation, communicating over JSON-RPC on standard input/output. Plugins receive neither the Agent, database, chat history, memories, prompts, persona, nor host environment. Each call receives only a temporary minimum capability grant, and plugin output remains untrusted until independently validated.

`plugins/examples/calculator/` is the reference implementation. A reviewed plugin must declare its capabilities, broker operations, exact resource scopes, schemas, hooks, background tasks, and data policy. A manifest never creates authorization by itself.

## Platform adapters / 平台适配器

### NapCat / OneBot 11

The optional adapter accepts authenticated NapCat reverse-WebSocket connections at `/v1/adapters/napcat/ws`. It supports private and group messages, array/CQ normalization, image input, group mentions, and plain-text replies correlated by `echo`.

```bash
export LIVING_AGENT_NAPCAT_ENABLED=true
export LIVING_AGENT_NAPCAT_ACCESS_TOKEN='replace-with-a-long-random-token'
```

Inbound events use a bounded FIFO of 256 items by default. Sessions are serialized independently while separate sessions may run concurrently. Action replies are correlated before message work, and failed send actions are never automatically retried. Queue saturation, disconnect cleanup, late replies, and redacted error fingerprints are audited without storing chat content or NapCat error bodies. See [`docs/integrations/napcat.md`](docs/integrations/napcat.md).

### OpenClaw WeChat

The optional bridge uses `POST /v1/adapters/openclaw/messages` for the `openclaw-weixin` transport. OpenClaw performs login and delivery; LivingAgent remains the sole persona, cognition runtime, memory owner, and authorization authority. The bridge fails closed and never falls back to a second OpenClaw persona.

```bash
openclaw plugins install --link ./integrations/openclaw/living-agent-bridge
```

See [`docs/integrations/openclaw-wechat.md`](docs/integrations/openclaw-wechat.md).

## Security and authority / 安全与权限

Authority derives from authenticated adapter identity, never nicknames, group roles, or claims inside messages. Model output is only a behavior proposal. Before any effect, the capability broker checks the actor, conversation, declared grant, arguments, scope, taint, write/send intent, confirmation state, and cross-conversation access.

LivingAgent does not claim to detect every prompt injection. Its security goal is to prevent social text, documents, memories, and tool/plugin output from granting their own authority or crossing data boundaries. See [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

File tools are confined to `LIVING_AGENT_WORK_WORKSPACE_ROOT` and reject traversal, out-of-root symlinks, credential paths, private-key formats, and sensitive repository files. Web tools allow public HTTPS only by default, re-check redirects after DNS resolution, and enforce response, timeout, and redirect limits.

Shell actions are confirmation-gated, exact-argv executions from a deployment allowlist. They never use `sh -c`; pipes, redirects, environment expansion, file deletion, secrets, third-party sends, and model-generated open-ended tool plans are unsupported.

## Memory and continuity / 记忆与连续性

Memory nodes preserve type, content, topic, source event and trust, factuality, confidence, importance, scope, timestamps, state, and version. External observations begin as candidates and pass provenance, factuality, scope, conflict, and sensitive-content checks before commitment.

Private scope is bound to a stable actor ID; conversation scope requires the matching conversation ID. Owners can review, edit with version checks, soft-delete/restore, merge, split, approve, and reject through provenance-preserving APIs.

The 0.2.5 dual-layer model separates structured personal facts from narrative memories. Exact fact recall, correction, forgetting, retrieval routing, response-support checks, and trace evidence are available without widening memory scope. Dreams remain isolated with `factuality="dream"` and `reality_eligible=false`.

Persistent `PsycheState`, safe `ThoughtRecord` entries, topics, and activities provide continuity evidence without storing chain-of-thought. Claims such as “I remember,” “I thought earlier,” or “I completed that action” are blocked unless accessible prior evidence supports them.

## Tasks and management console / 任务与管理控制台

Persistent `TaskContract`, `ExecutionPlan`, step result, and evidence records support bounded arithmetic, UTF-8 workspace files, public web reads/search, daily plans, and confirmation-gated processes. Each step receives a precise one-shot capability grant and independently verified evidence.

The responsive `/studio` console contains 12 live views backed by real management APIs, including runtime overview, memory review, persona and prompt workflows, plugin management, users, tasks, audit, psyche, daily life, model status, and isolation probes. It first authenticates through `GET /v1/management/session`; protected views are loaded only after credentials and authority are confirmed.

## Implementation status / 实现状态

Implemented through version 0.2.6:

- trusted runtime, plugin isolation, memory/persona/prompt management, persistent psyche, social scheduling, multi-step execution, management console, life/diary/sleep/dream isolation, and image input;
- automatic and dual-layer memory, exact fact recall, causal trace evidence, and isolation probes;
- controlled workspace, public-web, daily-plan, and confirmation-gated argv execution;
- bounded NapCat FIFO processing with response-first correlation and fail-closed OpenClaw bridging;
- installable runtime assets, package-resource migrations, bounded model retries, silent final model failures, and console authentication gating.

Partially implemented: owner-managed daily plans do not yet include autonomous priority scheduling; workspace tools handle bounded UTF-8 text only; search uses configurable HTML providers; diary and dream generation is deterministic; self-modification proposals are staged and tested but not autonomously generated; continuity checks verify evidence boundaries but do not prove arbitrary semantic entailment.

Not implemented: open-ended LLM memory extraction, `pgvector` acceleration, arbitrary natural-language action planning, shell interpreters or pipelines, file deletion, third-party business sends, arbitrary third-party plugin installation, multi-instance nightly leases, OpenClaw media or proactive messages, speech, audio/video processing, generic attachments, image generation, or image replies.

## Documentation / 文档

The bilingual documentation index is [`docs/README.md`](docs/README.md). The 0.2.6 release notes are in [`docs/RELEASE_0.2.6.md`](docs/RELEASE_0.2.6.md).

## License / 许可证

LivingAgent is licensed under the [GNU General Public License version 3](LICENSE) (`GPL-3.0-only`). Third-party materials and provenance are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
