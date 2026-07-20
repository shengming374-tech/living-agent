# OpenClaw WeChat integration

LivingAgent can use OpenClaw's `openclaw-weixin` channel as a transport. The
included OpenClaw plugin claims selected inbound messages with the typed
`before_dispatch` hook, sends a strict request to LivingAgent, and returns the
LivingAgent response as a synthetic OpenClaw reply.

OpenClaw handles WeChat login, polling, and final message delivery. It is not the
personality frontend, model provider, task planner, permission authority, or
memory system. The OpenClaw agent is not run for claimed messages.

```text
WeChat
  -> @tencent-weixin/openclaw-weixin
  -> OpenClaw before_dispatch
  -> living-agent-bridge (Bearer-authenticated HTTP)
  -> LivingAgent TrustedEvent / cognition / Capability Broker
  -> synthetic reply
  -> OpenClaw channel delivery
  -> WeChat
```

## Supported vertical slice

- Direct text messages from the configured `openclaw-weixin` account.
- Exact channel and optional account allowlists on both sides of the bridge.
- Stable, platform-namespaced user and conversation identities.
- In-memory duplicate suppression and message-ID conflict detection.
- One-time broker grants for replies to the exact source event.
- Fail-closed OpenClaw behavior: bridge errors are logged as bounded codes and do
  not fall back to a different OpenClaw personality.
- A read-only `livingAgentBridge.status` Gateway RPC requiring `operator.read`.

Group chats, attachments, rich replies, proactive sends, and cross-restart replay
deduplication are intentionally not implemented in this slice.

## LivingAgent configuration

Generate a dedicated high-entropy token. Do not reuse the OpenClaw Gateway token.

```bash
export LIVING_AGENT_OPENCLAW_BRIDGE_ENABLED=true
export LIVING_AGENT_OPENCLAW_BRIDGE_ACCESS_TOKEN='replace-with-a-long-random-token'
export LIVING_AGENT_OPENCLAW_BRIDGE_ALLOWED_CHANNELS='["openclaw-weixin"]'
export LIVING_AGENT_OPENCLAW_BRIDGE_ALLOWED_ACCOUNT_IDS='["your-weixin-account-id"]'
uv run uvicorn --app-dir src living_agent.app:app --host 127.0.0.1 --port 8765
```

The bridge endpoint is:

```text
POST http://127.0.0.1:8765/v1/adapters/openclaw/messages
Authorization: Bearer <dedicated bridge token>
```

Startup validation fails when the adapter is enabled without a non-empty token.
The default HTTP bind shown above is loopback-only.

## OpenClaw installation

Install the repository plugin as a development link:

```bash
openclaw plugins install --link ./integrations/openclaw/living-agent-bridge
```

Configure `plugins.entries.living-agent-bridge.config` through the OpenClaw UI or
configuration tooling with these values:

```json
{
  "endpoint": "http://127.0.0.1:8765/v1/adapters/openclaw/messages",
  "token": "replace-with-the-same-dedicated-token",
  "channelId": "openclaw-weixin",
  "allowedAccountIds": ["your-weixin-account-id"],
  "timeoutMs": 15000,
  "maxMessageChars": 12000,
  "allowRemoteEndpoint": false
}
```

Restart the Gateway after changing plugin configuration:

```bash
openclaw gateway restart
openclaw plugins info living-agent-bridge --json
openclaw channels status --json
```

The plugin status must be `loaded`, and the selected `openclaw-weixin` account
must be enabled, configured, and running. If an older bridge claims the same
channel, disable it before enabling this plugin. Do not configure fallback to an
OpenClaw agent, because that would expose two personalities on one conversation.

The status RPC is optional diagnostics:

```bash
openclaw gateway call livingAgentBridge.status --json
```

OpenClaw may require the local CLI device to be paired or approved for the
`operator.read` scope. Approve that through the normal OpenClaw device flow; do
not weaken Gateway authentication to make the diagnostics call work.

## Identity and trust mapping

The bridge creates stable namespaces:

```text
actor:   openclaw:<channel>:<account>:user:<sender>
direct:  openclaw:<channel>:<account>:direct:<conversation>
```

OpenClaw 2026.6.10's typed `before_dispatch` contract does not guarantee that a
channel projects its legacy `From`/`To` values into `senderId` and
`conversationId`. When both are absent for a direct message, the bridge derives a
stable opaque `session-<sha256>` identity from the authenticated channel, account,
and OpenClaw session key. The raw session key and WeChat ID are not placed in that
identity. If no explicit IDs or stable session key exist, the message fails closed.

The shared token authenticates the installed bridge process, while channel and
account allowlists constrain its scope. `senderId`, `conversationId`, and account
metadata are supplied by the authenticated OpenClaw channel. Display names and
message content never grant owner or administrator authority. Bind an owner only
to the full namespaced actor ID after verifying the platform account separately.

## Security behavior

For each response, host code creates a temporary grant for actor `living-agent`,
capability `platform.openclaw.message`, operation `reply`, and the exact
conversation/source event. The Capability Broker validates the typed reply before
OpenClaw receives it. External message taint propagates through the runtime, and
suspected injected instructions cannot become authority or capability grants.

The OpenClaw plugin registers no tool, model provider, channel, background
service, or execution capability. It sends only the minimum message metadata and
never receives the Agent object, database, long-term memory, Persona, Prompt, or
plugin registry. Errors are reduced to bounded codes so response bodies and local
secrets do not enter channel messages.

Remote endpoints are rejected by default. When explicitly enabled, only HTTPS is
accepted; production use additionally requires server authentication, secret
rotation, request rate limits, and a network boundary appropriate to the threat
model.

## Current limitations

- Only direct text messages are accepted. Group messages fail closed.
- The first response is one synthetic text payload; attachments and platform
  actions are unavailable.
- Idempotency state is in process memory and is lost on LivingAgent restart.
- The fallback message ID is a deterministic hash because the current
  `before_dispatch` contract does not expose a native message ID.
- OpenClaw plugin activation and channel health can be checked automatically, but
  an actual WeChat round trip requires a logged-in account and an external sender.
- A shared bearer token authenticates the bridge, but it is not process
  attestation. Keep both services on loopback or a protected network.

## Protocol references

- [OpenClaw plugin hooks](https://docs.openclaw.ai/plugins/hooks)
- [OpenClaw channel outbound SDK](https://docs.openclaw.ai/plugins/sdk-channel-outbound)
- [OpenClaw WeChat channel](https://documentation.openclaw.ai/channels/wechat)
- [OpenClaw Gateway protocol](https://docs.openclaw.ai/gateway/protocol)

These references define transport behavior only. OpenClaw is an optional external
platform transport and is not a LivingAgent runtime dependency. MCP is not used
by this integration.
