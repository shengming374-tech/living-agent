# NapCat OneBot 11 integration

LivingAgent provides a host-owned NapCat platform adapter at
`/v1/adapters/napcat/ws`. NapCat acts as a reverse WebSocket client: it connects
to LivingAgent, pushes OneBot 11 events, and receives API actions on the same
connection.

## Supported vertical slice

- Bearer-token authentication, with the official `access_token` query fallback.
- `X-Self-ID` validation and per-frame `self_id` consistency checks.
- OneBot 11 private and group `message` events.
- Array messages and CQ-code string messages.
- Group `@bot` detection for the existing LivingAgent TurnGate.
- Lifecycle and heartbeat frame validation without cognitive ingestion.
- Concurrent event handling and `echo`-correlated action responses.
- `send_private_msg` and `send_group_msg` replies through the same WebSocket.
- Action timeout/failure isolation and structured audit records.

## LivingAgent configuration

Set a strong shared token. The raw token is represented by Pydantic `SecretStr`
and is never written to prompt or audit output.

```bash
export LIVING_AGENT_NAPCAT_ENABLED=true
export LIVING_AGENT_NAPCAT_ACCESS_TOKEN='replace-with-a-long-random-token'
uv run uvicorn --app-dir src living_agent.app:app --host 127.0.0.1 --port 8000
```

Optional limits:

```bash
export LIVING_AGENT_NAPCAT_ACTION_TIMEOUT_SECONDS=5
export LIVING_AGENT_NAPCAT_MAX_MESSAGE_CHARS=12000
export LIVING_AGENT_NAPCAT_MAX_FRAME_BYTES=1048576
export LIVING_AGENT_NAPCAT_MAX_IN_FLIGHT_EVENTS=16
```

Startup validation fails when NapCat is enabled without a non-empty token.

## NapCat configuration

In NapCat WebUI, create a **WebSocket Client** network configuration:

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

The `token` must match `LIVING_AGENT_NAPCAT_ACCESS_TOKEN`. NapCat supplies the
Bearer header and `X-Self-ID`. Prefer the header; query-string tokens may be
captured by proxy access logs. When containers are separate, replace `127.0.0.1`
with the LivingAgent service name or reachable host.

## Identity and conversation mapping

NapCat data is namespaced so QQ IDs cannot collide with another platform:

```text
actor:        napcat:<bot_qq>:qq:<sender_qq>
private:      napcat:<bot_qq>:private:<sender_qq>
group:        napcat:<bot_qq>:group:<group_qq>
```

QQ nickname, group card, and OneBot sender `role` never establish LivingAgent
authority. To bind the configured owner to a QQ account, use the full actor ID,
for example:

```bash
export LIVING_AGENT_OWNER_ID='napcat:123456789:qq:987654321'
```

The WebSocket token authenticates the NapCat adapter connection. `X-Self-ID`
provides bot namespacing but is not a separate credential; deployments serving
multiple untrusted NapCat instances should use separate LivingAgent instances or
an authenticating reverse proxy.

## Outbound security

The adapter cannot send arbitrary model actions. For one user-visible Runtime
reply, host code creates one temporary grant bound to:

- actor `living-agent`;
- capability `platform.napcat.message`;
- operation `reply`;
- the exact conversation and source TrustedEvent;
- one use only.

The Capability Broker validates the typed target and message arguments before the
adapter sends anything. A member cannot use `reply`, and dangerously tainted
input cannot authorize the write. Outbound model text is encoded as a OneBot
`text` segment, so CQ-looking text cannot turn into a mention, image, file, or
other rich operation. NapCat response wording is treated as untrusted transport
data and is neither prompted nor logged; audit retains only bounded status fields.

## Current limitations

- Reverse WebSocket only; forward WebSocket, HTTP API, and HTTP webhook modes are
  not implemented.
- Only private/group message events are cognitive inputs. Notice and request
  events are ignored and audited.
- Replies are plain text. Images, files, voice, replies/quotes, reactions, group
  administration, and NapCat extension APIs are not exposed.
- There is no unsolicited or scheduled message API.
- OneBot `message_id` replay deduplication is not persisted yet. Duplicate events
  from an upstream replay can therefore produce duplicate replies.
- A live NapCat/QQ account is external infrastructure and is not part of the
  automated test environment.

## References

- [NapCat WebSocket documentation](https://napneko-napcatqq.mintlify.app/api/network/websocket)
- [NapCat HTTP API documentation](https://napneko-napcatqq.mintlify.app/api/network/http)
- [OneBot 11 WebSocket protocol](https://github.com/botuniverse/onebot-11/blob/master/communication/ws.md)
- [OneBot 11 message events](https://github.com/botuniverse/onebot-11/blob/master/event/message.md)

These documents were consulted for protocol behavior only. LivingAgent does not
depend on NapCat Python/Node packages and NapCat is not imported into the core
runtime.
