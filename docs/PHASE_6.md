# Phase 6 completion record

Completed on 2026-07-21.

## Executive contracts and planning

- `TaskContract`, `ExecutionPlan`, `PlanStep`, `PlannedAction`, `TaskRun`, and
  `TaskStepResult` are strict Pydantic contracts separate from database models.
- Deterministic task understanding recognizes single or multi-step arithmetic,
  optional task-report storage, and owner confirmation commands in Chinese or
  English. Unknown text remains social chat rather than becoming an action.
- Plans are topologically ordered, bounded to 16 steps, and validated against the
  authenticated requester, provenance, allowed capabilities, forbidden
  operations, exact handler metadata, report scope, and confirmation requirements.

## Execution and evidence

- Every calculator step receives a distinct one-time grant and isolated plugin
  process. Host verification recomputes arithmetic and rejects forged output.
- Timeout, crash, and protocol failures retry only the current step up to its
  declared bound. Semantic/schema/permission failures stop immediately and mark
  unstarted steps skipped.
- Plan completion requires every step to be completed with handler-specific
  evidence. Executive code returns structured state; Social Cognition alone
  renders visible language.
- Task runs, plans, attempts, outputs, evidence, pending confirmation, provenance,
  activity IDs, and optimistic versions persist in PostgreSQL-compatible tables.

## Confirmation and recovery

- `task.report/write` is a host-owned database capability with strict arguments
  and exact `tasks/{task_id}/report` scope. It cannot access files, network,
  prompts, memories, plugins, or the Agent object.
- Owner-originated writes first stop at `waiting_confirmation`. Members cannot
  authorize writes, and dangerous taint is denied even when an owner confirms.
- API confirmation is owner-only. Chat confirmation additionally requires the
  same conversation; it cannot expose or approve another conversation's pending
  task.
- Pending tasks survive restart. Interrupted calculator work may retry within its
  bound. Interrupted writes require confirmation again and use idempotent report
  commits. Owners can cancel a non-terminal task without producing its write.

## Excluded from Phase 6

- The first executable catalog contains arithmetic and task-report storage only.
  Arbitrary model-generated plans, filesystem tools, network tools, unsolicited
  messaging, and Shell execution remain unavailable.
- Multimodal input/output is deferred to `0.2.0` and is not part of this phase.
- Distributed task leases are required before running multiple Runtime instances
  against one database.

## Phase gate

- `pytest`: 169 passed.
- `ruff check .`: passed.
- `mypy src`: passed for 108 source files.
- OpenClaw bridge `node --test`: 13 passed.

Tests cover multi-step plugin execution, topological dependencies, plan actor and
scope substitution, independent evidence, transient retry, terminal failure,
dependent-step skipping, owner-only APIs, same-conversation chat confirmation,
tainted and unauthorized writes, cancellation, pending-task restart persistence,
interrupted read recovery, write re-confirmation after restart, activity
reconciliation, migrations, and all earlier runtime behavior.
