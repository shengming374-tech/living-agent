# Phase 5: biomimetic speech and interruption

Completed on 2026-07-21.

## Delivered

- Bounded `ConversationMomentum` and all four `TurnDecision` modes.
- One short `react` unit or one-to-three semantic `engage` units without fixed
  three-message behavior or punctuation-only fragmentation.
- Typed `SpeechUnit` and `UtteranceSession` state with ordered delivery counts.
- Runtime-owned, per-platform and per-conversation utterance generations.
- Immediate first-unit delivery and configurable deterministic continuation
  pacing, with real waits disabled by test configuration.
- Cancellation of pending delays and unsent units when a newer inbound arrives.
- Suppression of an older model result that finishes after a newer turn.
- Fresh planning from the new inbound context, linked to the cancelled Session by
  `utterance.replanned` audit evidence.
- Delivery-aware persistence: generated text is not conversation history until a
  transport confirms it was sent.
- Durable Session persistence for units, source event, scope, generation,
  started/delivered counts, memory-use references, and terminal state.
- Startup recovery of the newest in-flight Session per platform/conversation
  scope. Recovery never schedules an automatic resend.
- Chat API, NapCat, and OpenClaw integration. OpenClaw rejects late receipts for a
  superseded Session and accepts in-order receipts for a still-current Session
  issued before a LivingAgent restart.

## Behavioral boundaries

- Replanning never continues or edits the stale remainder. The latest inbound
  event runs through the normal trust, momentum, Social/Executive, and critic
  pipeline to produce a fresh Session.
- The first unit is non-cancellable once sending has begun. Remaining cancellable
  units stop before send; an already-started transport action may still complete
  and is recorded only if its adapter reports success.
- Delay selection is deterministic midpoint pacing, not random human simulation.
- `react` remains one unit. `engage` can use fewer than its preferred count when
  the model produced fewer genuine semantic ideas; the host does not duplicate or
  invent filler to reach a quota.
- Task results remain structured Executive output rendered by Social Cognition.

## Security and correctness

- Each adapter keeps its existing exact-event Capability Grant. Utterance state
  changes timing and cancellation, never authority.
- Delivery indices must be recorded in order, preventing a later receipt from
  falsely marking skipped units as spoken.
- Agent-message persistence and Session delivery progress commit in one database
  transaction. Replayed receipts are idempotent and cannot duplicate history.
- Audit records planned, interrupted, and replanned Sessions without storing
  hidden reasoning. Startup records `utterance.recovered` with
  `automatic_resend=false`.
- Cancelled or failed units do not affect momentum, memory-usage evidence, or
  continuity claims.

## Verification

- Full Python suite: `182 passed`.
- Ruff: passed. Strict mypy: passed across 115 source files.
- OpenClaw bridge suite: `13 passed`, including server-provided pacing,
  cancellation, late-response suppression, and delivery receipts.
- Restart-recovery suite: `2 passed`, covering in-order continuation,
  idempotency, stale receipt rejection, and generation continuity.
- Focused Runtime, Chat API, NapCat, OpenClaw, momentum, and utterance tests:
  `57 passed`.

## Deferred

- Multimodal speech/media output, scheduled for version `0.2.0`.
