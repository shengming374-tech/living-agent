# LivingAgent

LivingAgent is a greenfield runtime for a persistent digital persona with natural
social participation and reliable, policy-controlled task execution. It is not a
claim of consciousness and does not fabricate a biological body or life history.

The implemented foundation includes trusted ingress, brokered execution,
source-aware long-term memory, managed Persona/Prompt versions, and persistent
psyche evidence. Interruptible speech, general planning, and the management UI
remain staged features and are listed explicitly below.

## Goals

- One externally consistent persona with separate social and executive cognition.
- Source-aware events and context instead of flattening all text into instructions.
- Code-enforced capability decisions outside the language model.
- Auditable tasks, evidence, memory provenance, and state changes.
- Native least-privilege plugins isolated from the main runtime.

## Non-goals

- Simulating biological embodiment or claiming real consciousness.
- Forking, wrapping, importing, or requiring MaiBot.
- Using MaiBot or MCP as the personality frontend or native plugin runtime.
- Arbitrary shell execution, agent-approved self-deployment, or chat-based policy edits.

## Architecture

```text
Platform/API input
      |
      v
Trust Boundary -> TrustedEvent -> Turn Gate
      |                              |
      |                     Social Cognition
      |                              |
      +-> typed Context Compiler <- structured Executive result
                                     |
                              Action Proposal
                                     |
                              Policy Engine
                                     |
                           Capability Broker
                          / deny ask allow \
                         v                 v
                 host capability    plugin subprocess
                         \                 /
                          verified evidence
                                  |
                         Social Cognition -> user

All decisions/effects ---------------------> Audit Log
```

Executive Cognition never sends natural-language messages. It returns structured
results that Social Cognition may express in the persona's voice.

## Development

Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) are recommended.

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run mypy
```

Run the development API from the project directory:

```bash
uv run uvicorn --app-dir src living_agent.app:app --reload
```

Then request `GET /health` or submit an authenticated-adapter envelope to
`POST /v1/chat`. Configuration defaults live in `config/default.yaml`; copy
`.env.example` values into the process environment for deployment overrides.

## Model configuration

The deterministic `MockLLMProvider` remains the default and requires no
credentials. An `openai_compatible` provider can call a host-configured cloud
`/chat/completions` API. `ROOT_POLICY` remains a system message; all social,
memory, task, document, tool-result, and capability sections are sent as typed
user-message JSON with provenance and taint labels. Responses are bounded and
validated, hidden reasoning fields are ignored, and audit stores only provider,
model, token counts, and bounded errors. See
[`docs/integrations/cloud-model-api.md`](docs/integrations/cloud-model-api.md).

Secrets belong in environment-backed settings and must never appear in prompt or
audit previews.

Embeddings have an independent Provider boundary. The default deterministic Mock
requires no credentials; `openai_compatible` calls a configured `/embeddings`
endpoint with strict response, size, index, finite-number, and dimension checks.
Owner-only `GET /v1/embeddings/status` and `POST /v1/embeddings` provide a tested
vertical slice. Sending text to a remote provider requires an exact one-time
`model.embedding.generate` Capability Broker grant and is audited without storing
input text, vectors, keys, or upstream error bodies. See
[`docs/integrations/embeddings.md`](docs/integrations/embeddings.md).

## Native plugins

The native host discovers strict manifests and invokes each plugin call in a new
isolated Python subprocess using JSON-RPC over stdio. Plugins receive no Agent,
database, chat-history, memory, prompt, persona, or host environment object. Every
invocation carries a temporary, minimal capability grant, and plugin output is
tainted as untrusted until independently verified. MCP may later be implemented as
an optional connector adapter; it is not a core dependency.

The calculator at `plugins/examples/calculator/` is the reference implementation.
To add a reviewed plugin:

1. Add `plugins/examples/<plugin>/manifest.yaml` and the declared entrypoint module.
2. Declare each operation's capability, broker operation, exact resource scope,
   input schema, output schema, hooks, background tasks, and data policy.
3. Expose one `invoke(params) -> dict` function. Do not import LivingAgent or expect
   host objects, secrets, installation hooks, or shell access.
4. Register host-owned Pydantic argument/output validation and policy for any new
   capability. A manifest declaration alone never creates a grant.
5. Add crash, timeout, schema, permission, taint, and verifier tests, then enable it
   as the owner through `POST /v1/plugins/{id}/enable`.

`GET /v1/plugins` lists discovery and enabled state. These management endpoints use
the development owner header described under security limitations.

## NapCat / OneBot 11 adapter

An optional host-owned platform adapter accepts NapCat reverse WebSocket
connections at `/v1/adapters/napcat/ws`. It supports authenticated private/group
message ingestion, array and CQ-string normalization, group `@bot` participation,
and `echo`-correlated plain-text replies over the same connection.

Enable it with a shared token:

```bash
export LIVING_AGENT_NAPCAT_ENABLED=true
export LIVING_AGENT_NAPCAT_ACCESS_TOKEN='replace-with-a-long-random-token'
```

Configure a NapCat WebSocket Client URL such as
`ws://127.0.0.1:8000/v1/adapters/napcat/ws`, using the same token and preferably
`messagePostFormat: array`. QQ identities and conversations are platform- and
bot-namespaced; nicknames, group cards, and OneBot group roles never grant
LivingAgent authority.

Every outbound reply receives a one-time Capability Broker grant bound to the
exact source event and conversation. Replies are encoded as a OneBot `text`
segment, preventing CQ-looking model output from becoming a rich action. See
[`docs/integrations/napcat.md`](docs/integrations/napcat.md) for the NapCat WebUI
example, identity mapping, security model, limits, and official protocol sources.

## OpenClaw WeChat bridge

An optional OpenClaw plugin connects the `openclaw-weixin` channel to LivingAgent
through `POST /v1/adapters/openclaw/messages`. OpenClaw handles WeChat login and
delivery; LivingAgent remains the only personality, cognition runtime, memory
owner, and permission authority. Claimed messages are handled before OpenClaw's
model dispatch and never fall back to another OpenClaw personality.

The bridge uses a dedicated bearer token, exact channel/account allowlists,
platform-namespaced identities, bounded in-memory replay suppression, strict
schemas, and a one-time Capability Broker grant for the exact source-event reply.
It defaults to loopback and direct text only. Install the included plugin with:

```bash
openclaw plugins install --link ./integrations/openclaw/living-agent-bridge
```

See [`docs/integrations/openclaw-wechat.md`](docs/integrations/openclaw-wechat.md)
for LivingAgent/OpenClaw configuration, identity mapping, validation commands,
security behavior, current limits, and protocol references.

## Permission model and prompt injection

Authenticated adapter identity, never a nickname or message claim, determines
authority. Language-model output is an action proposal only. The capability
broker checks actor, session, declared grant, arguments, scope, taint, write/send
intent, confirmation, and cross-session access before execution.

LivingAgent does not promise to recognize every prompt injection. It is designed
so malicious social text, documents, memories, and tool/plugin results cannot by
themselves grant permission or cross a data boundary. See
[`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

## Memory design

Implemented memory nodes carry type, content, subject, source event IDs and trust,
factuality, confidence, importance, scope, timestamps, status, and version.
External observations are persisted as candidates and pass source validation,
factuality classification, scope enforcement, and conflict checks before an owner
commit. Authority, credentials, policies, plugin approval, privileged phrases,
dream facts, and role-play identities cannot auto-enter core memory.

`/v1/memories` supports scope-first search and management. Private scope is bound
to a stable actor ID; conversation scope is visible only with the matching
conversation ID; global candidates require owner-authored source events. Owner
operations support version-checked edits, soft delete/restore, merge, and split.
Source event, version, and response-usage endpoints preserve provenance. Automatic
model extraction and semantic/vector retrieval are not implemented. The embedding
Provider/API slice does not automatically export or vectorize committed memories.

## Persona and prompt changes

Persona is layered across identity, values, traits, speech, boundaries, and growth
files with strict schemas that cannot hold authority policy. Persona and Prompt
APIs implement edit, diff, validate, stage, test, deploy, immutable history,
rollback, and audit. Deployments use optimistic versions and return their recovery
version; stale or untested stages cannot deploy.

At startup the runtime validates all six deployed persona layers and compiles them
with the deployed social-response Prompt into trusted model instructions. The
social Prompt accepts only the validated persona name; user message text remains
in its typed request section and is never interpolated into system instructions.
The current PsycheState is supplied separately as `PSYCHE_STATE`, with source and
taint metadata preserved.

Root-policy stage/deploy/rollback additionally requires the owner and
`X-Second-Factor`. Configure only its digest:

```bash
export LIVING_AGENT_ROOT_PROMPT_SECOND_FACTOR_SHA256="$(printf %s 'your-secret' | shasum -a 256 | cut -d ' ' -f 1)"
```

Root changes must pass authority, Capability Broker, model-cannot-grant, and
untrusted-data regression checks. They activate after restart. Chat messages have
no Persona or Prompt mutation route, and an agent proposal cannot approve itself.
`POST /v1/prompts/context-preview` shows the actual currently loaded typed context
with secrets redacted.

## Persistent psyche and continuity evidence

One persistent PsycheState stores bounded valence, arousal, current focus,
focus salience, unresolved-topic IDs, and the current activity. Values decay
toward neutral using `LIVING_AGENT_PSYCHE_DECAY_HALF_LIFE_HOURS`; historical
ThoughtRecords are not rewritten by decay. Runtime appraisal creates a safe,
structured `reaction` or `suppressed_reply` summary for every ingested chat event
without storing model chain of thought.

Owner-only `/v1/psyche` APIs expose state, safe ThoughtRecords, unresolved topics,
and activity evidence. Source event IDs must exist before a thought, topic, or
activity can be recorded. Calculator work creates a running activity, finishes it
as completed or failed, attaches evidence IDs, and clears current activity.

The Continuity Critic checks observable model claims before Social Cognition may
render them. “I remember” needs an accessible committed memory; “I thought about
that earlier” needs an earlier ThoughtRecord whose source belongs to the same
conversation; and action claims need completed activity or verified tool audit
evidence. Unsupported claims are blocked and audited. Viewpoint-change claims are
blocked until versioned viewpoint history exists.

Chat generation also receives a bounded recent-conversation window containing the
last user and LivingAgent turns for the same conversation only. These turns stay in
the typed, taint-labelled data section and are not permanent memory; they provide
short-term conversational continuity without widening memory scope or authority.

## Reference boundary

MaiBot is used only as read-only mechanism research. It is not a dependency and
does not run with LivingAgent. The exact GPL-3.0 reference revision and inspected
files are recorded in [`docs/research/provenance.md`](docs/research/provenance.md);
no code or prompts were borrowed.

## Implementation status

Implemented: Phase 0 research and architecture; Phase 1 secure runtime; and the
Phase 2 native plugin slice. The latter includes manifest discovery, owner enable
state, isolated per-call subprocesses, JSON-RPC, timeout/crash handling, one-time
broker grants, Calculator, structured task contracts, independent result
verification, social reporting, and audit evidence. The Phase 3 memory slice adds
candidates, a source/factuality firewall, scoped versioned nodes, lifecycle APIs,
provenance, and usage history. Phase 3 also includes six-layer Persona management
and eight-category Prompt management with staging, tests, recovery, and rollback.
Phase 4 adds persistent PsycheState, safe ThoughtRecords, unresolved topics,
calculator activity evidence, restart recovery, state decay, and evidence-gated
continuity claims. The runtime also supplies the six-layer persona, deployed
social Prompt, and current PsycheState to chat generation without elevating user
text into system instructions. A partial Phase 5 slice adds typed
`UtteranceSession`/`SpeechUnit` output: `react` keeps one short unit while
`engage` may deliver two or three equally short semantic units through the exact
same-event platform grant. Recent trusted turns also produce a bounded
`ConversationMomentum`, so acknowledgements, short questions, and consecutive
user messages do not all receive the same length-based decision. The optional
NapCat compatibility slice adds a tested OneBot
11 reverse-WebSocket Platform Adapter without making NapCat a runtime dependency.
The optional OpenClaw compatibility slice adds a tested, fail-closed bridge from
the `openclaw-weixin` channel without making OpenClaw a runtime dependency or a
second personality frontend.
The embedding compatibility slice adds deterministic Mock and strict
OpenAI-compatible providers plus an owner-only, brokered generation API. It does
not yet add vector persistence or memory ranking.
The cloud chat compatibility slice adds a strict OpenAI-compatible Chat
Completions provider with typed context boundaries and isolated failure handling.
It remains disabled until a deployment supplies its endpoint, model ID, and key.

Partially implemented: activities currently describe calculator execution, not a
general daily-activity system; continuity checks cover memory, prior-thought, and
execution claims, while viewpoint changes remain blocked without viewpoint
versions. The critic validates evidence existence, accessibility, time, status,
and conversation scope; it does not yet independently prove semantic entailment
between arbitrary free-form claim text and the referenced record.

Not yet implemented: automatic memory extraction/vector retrieval, runtime-level
replanning of interrupted speech, general
multi-step executive planning, Control Studio,
arbitrary third-party plugin installation, journaling, sleep, and dream isolation.
OpenClaw group/media/proactive messaging and persistent bridge idempotency are
also not implemented. The OpenClaw and NapCat adapters cancel unsent follow-up
units when a newer inbound message reaches the same conversation.
This section is updated only after executable, tested vertical slices land.

## Security limitations

HTTP authentication, OS-level plugin sandboxing, tamper-evident audit storage,
provider privacy guarantees, resource quotas, and production deployment hardening
are not supplied by the current runtime. `/v1/chat` is an adapter ingress and its
`authenticated` identity flag is only trustworthy behind an authenticated adapter
or gateway. The development `X-Actor-ID` audit header is not production-grade
authentication. Never run unreviewed plugin code merely because process isolation
exists. The subprocess boundary minimizes data and contains crashes/timeouts, but
it is not an OS sandbox against hostile Python file or network syscalls; production
third-party plugins require a container, platform sandbox, or VM.
