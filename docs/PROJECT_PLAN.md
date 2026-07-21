# LivingAgent delivery plan

## Architecture objective

LivingAgent is a standalone runtime around one externally visible digital
persona. Social Cognition owns participation and expression; Executive
Cognition returns structured task evidence and cannot send user-facing text.
Every external effect crosses a code-enforced capability broker.

## Phase status

| Phase | Scope | Current status |
| --- | --- | --- |
| 0 | Research, ADRs, threat model, tooling baseline | Complete |
| 1 | Trusted event to audited chat response | Complete |
| 2 | Brokered calculator plugin in an isolated process | Complete |
| 3 | Managed memory, persona, and prompt APIs | Complete |
| 4 | Persistent psyche and safe thought records | Complete |
| 5 | Momentum, utterance sessions, interruption | Complete |
| 6 | Multi-step executive kernel and verification | Complete |
| 7 | Control Studio | Complete |
| 8 | Activities, journaling, dream isolation, proposals | Planned |

Each implemented phase must pass pytest, Ruff, and mypy before its phase commit.
Later-phase schemas are added only when needed by an executable slice, avoiding
placeholder modules.

The current Phase 5 slice derives a ten-minute `ConversationMomentum` from recent
trusted turns. It distinguishes a new exchange, back-and-forth conversation, and
consecutive user messages; the turn gate keeps acknowledgements brief while
allowing short questions or continued thoughts to receive a few short units.
Direct messages and explicit mentions remain responsive. Optional unmentioned
group participation uses a deterministic consecutive-user-turn threshold and
time-since-last-agent cooldown, produces one short reaction, and cannot be
triggered by a suspected instruction. The frequency calculation can inspect up to
128 persisted turns while model context remains limited to the latest eight.
`UtteranceSession.sent_count` and state advance only when a transport records
delivery. Recent conversation history is built from those delivered units rather
than the complete generated plan. A shared coordinator now owns per-platform,
per-conversation generations: a newer inbound turn cancels the active Session,
wakes any continuation delay, suppresses late older model output, and links the
fresh Session through an audited `utterance.replanned` record. It deterministically
uses the configured delay midpoint; tests disable waits through Settings.

Authenticated social events now auto-register a stable platform identity with
display name, first/last seen timestamps, message count, and last conversation.
Registration occurs after trust normalization and never stores authority.
Owner-only read APIs expose profiles; unauthenticated and non-social sources are
excluded.

Platform compatibility slice: NapCat OneBot 11 reverse WebSocket is implemented
as a host-owned adapter with authenticated ingress and brokered same-event
replies. It can deliver the short units in a brokered `UtteranceSession`
sequentially. A newer inbound message in the same conversation cancels any units
that have not begun sending and records started, delivered, and unsent counts in
the audit log.

OpenClaw WeChat compatibility is implemented as a transport bridge using the
typed `before_dispatch` synthetic-reply contract. It authenticates and namespaces
ingress, applies channel/account allowlists, brokers exact same-event replies, and
fails closed without delegating personality or permissions to OpenClaw. A new
inbound message cancels unsent follow-up units in that same conversation and
suppresses an older model response that finishes late. The server also rejects
late delivery receipts for an interrupted Session, preventing cancelled text from
entering conversation history. Direct
text is implemented; group/media/proactive messaging and persistent replay keys
remain future work.

Embedding provider compatibility is implemented as a separate vertical slice:
deterministic Mock and OpenAI-compatible providers, strict transport/response
validation, owner-only API access, and a brokered one-time external-send grant.
Runtime chat now has local lexical recall after repository scope filtering, with
reality-factuality filtering and delivered-response usage records. Vector
persistence, memory backfill, embedding ranking, and index migration remain
planned rather than implied by this slice.

Cloud chat compatibility is implemented as a separate provider slice using
OpenAI-compatible non-streaming Chat Completions. It preserves root/data context
separation, validates bounded final text, isolates provider failures, and records
only safe operational metadata. A real deployment remains configuration-dependent
and requires an owner-supplied endpoint, model ID, and credential.

Phase 6 is implemented as a persistent typed task kernel. Deterministic task
understanding creates bounded calculator/report plans; every step carries one
CapabilityRequest, dependency set, retry bound, result, and evidence. The runner
supports multiple plugin calls, stops dependent work after failure, retries only
transient process failures, independently verifies completion, survives restart,
and never resumes an interrupted write without renewed owner confirmation.
Owner APIs expose task status, reports, confirmation, and cancellation. Social
Cognition alone renders the structured result. The first action catalog is
deliberately limited to verified arithmetic and confirmed database reports.

Phase 7 is implemented as a same-origin Control Studio bundled with FastAPI. It
operates the existing memory, Persona, Prompt, plugin, task, user, audit, and
version APIs, adds read/revoke capability inventory, and adds a read-only Behavior
Simulator. The simulator follows the real trust, momentum, turn-gate, and bounded
executive proposal paths without event/task/audit persistence, model/plugin calls,
or external effects. The Studio cannot mint capability grants.

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
   visible persona as one short reaction or a few short semantic units.
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
evidence constraints. Phase 5 added interruptible, paced, replanned speech.
Phase 6 adds persistent
typed task planning, execution recovery, and evidence verification. Phase 7 added
the owner control surface after those persistence and security contracts matured.
Phase 8 remains last because journaling, dream, and daily-activity features need
strict fact-isolation and self-modification approval semantics.

Multimodal input and output are scheduled for version `0.2.0`, after the current
text/runtime phases. Existing media segment placeholders are transport metadata,
not image, audio, video, or attachment understanding.
