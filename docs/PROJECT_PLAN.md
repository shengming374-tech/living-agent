# LivingAgent delivery plan

## Architecture objective

LivingAgent is a standalone runtime around one externally visible digital
persona. Social Cognition owns participation and expression; Executive
Cognition returns structured task evidence and cannot send user-facing text.
Every external effect crosses a code-enforced capability broker.

## Phase status

| Phase | Scope | Status at project creation |
| --- | --- | --- |
| 0 | Research, ADRs, threat model, tooling baseline | Complete |
| 1 | Trusted event to audited chat response | Complete |
| 2 | Brokered calculator plugin in an isolated process | Complete |
| 3 | Managed memory, persona, and prompt APIs | Complete |
| 4 | Persistent psyche and safe thought records | Complete |
| 5 | Momentum, utterance sessions, interruption | Planned |
| 6 | Multi-step executive kernel and verification | Planned |
| 7 | Control Studio | Planned |
| 8 | Activities, journaling, dream isolation, proposals | Planned |

Each implemented phase must pass pytest, Ruff, and mypy before its phase commit.
Later-phase schemas are added only when needed by an executable slice, avoiding
placeholder modules.

Platform compatibility slice: NapCat OneBot 11 reverse WebSocket is implemented
as a host-owned adapter with authenticated ingress and brokered same-event
replies. It does not change the Phase 5 status because interruptible multi-unit
utterance sessions are still planned.

OpenClaw WeChat compatibility is implemented as a transport bridge using the
typed `before_dispatch` synthetic-reply contract. It authenticates and namespaces
ingress, applies channel/account allowlists, brokers exact same-event replies, and
fails closed without delegating personality or permissions to OpenClaw. Direct
text is implemented; group/media/proactive messaging and persistent replay keys
remain future work.

## Minimum viable vertical slice

1. An authenticated adapter submits a message with a platform identity.
2. The trust boundary creates a `TrustedEvent`, assigning authority in code and
   tainting message content as external data.
3. A turn gate produces a structured `TurnDecision`.
4. A context compiler labels policy, owner request, social chat, untrusted data,
   task, memory, and capabilities without flattening their trust semantics.
5. A model provider proposes text or a structured action, but grants nothing.
6. The capability broker validates identity, session, schema, scope, taint, write
   intent, confirmation, cross-session access, and external sending.
7. Runtime or a subprocess plugin executes only an allowed grant.
8. Verification produces structured evidence; Social Cognition renders the one
   visible response.
9. Security decisions and effects are written to an append-only application
   audit service inaccessible to plugin code.

## Delivery criteria for this execution

### Phase 0

- Pinned mechanism research and provenance with no borrowed source code.
- Explicit independent-runtime and license boundary.
- ADRs, threat model, assumptions, packaging, lint, type, and test baseline.

### Phase 1

- FastAPI health and chat endpoints backed by migrated SQLite.
- Trusted events, authority, taint propagation, audit log, capability decisions,
  context compiler, event bus, and deterministic mock model.
- Tests for impersonation, untrusted instructions, unauthorized writes, audit,
  migrations, health, and chat.

### Phase 2

- Strict manifest and request/result schemas.
- Plugin discovery plus one subprocess per invocation, JSON-RPC over stdio,
  minimal environment, timeout, termination, and crash isolation.
- Calculator task contract through broker, verified result, and social rendering.

## Later milestones

Phase 3 added a source-aware memory firewall and management/version APIs before
long-term recall claims were enabled. Phase 4 added persistent safe thought
summaries, psyche state decay, unresolved topics, task activities, and continuity
evidence constraints. Phase 5 adds interruptible speech. Phase 6 adds general task
planning and evidence verification. Phases 7 and 8 remain last because
administration and dream/activity features must rest on mature security and
persistence semantics.
