# Phase 4 completion record

Completed on 2026-07-20 in the
`feat(psyche): add persistent thought and continuity evidence` commit.

## Persistent psyche

- Alembic revision `0004_persistent_psyche` creates PsycheState, ThoughtRecord,
  unresolved-topic, and activity tables using PostgreSQL-compatible SQLAlchemy
  types.
- A single `primary` state persists valence, arousal, current focus, focus
  salience, unresolved-topic IDs, and current activity across restart.
- Explicit and startup decay use a configurable half-life. Valence and arousal
  approach neutral; focus is cleared below a bounded salience threshold.
- Every chat event creates either a `reaction` or `suppressed_reply` record after
  TurnDecision. These are deterministic, safe summaries and never raw model chain
  of thought.
- Thought, topic, and activity records require existing TrustedEvent sources.
  Owner control APIs can inspect/update state, inspect/create/resolve thoughts,
  create/resolve topics, and inspect activities. All mutations are audited.

## Activity evidence

- Calculator execution starts a `calculator_task` activity before the plugin call.
- Completion records success/failure and evidence IDs, then clears current
  activity without erasing historical activity.
- Executive Cognition still returns structured task results; only Social
  Cognition renders user-visible language.

## Continuity critic

- Model responses carry structured `ClaimEvidence` IDs separately from text.
- Memory claims require an accessible committed memory in the active scope.
- Prior-thought claims require an existing earlier ThoughtRecord whose source
  events all belong to the active conversation.
- Action claims require completed same-conversation activity or verified
  same-conversation tool audit entries.
- Viewpoint-change claims are blocked because viewpoint version history is not
  implemented. Unsupported claims produce a Social Cognition fallback and a
  `continuity.blocked` audit record.
- Model response text and raw reasoning are not stored in ThoughtRecords or audit
  details.

Evidence validation in this phase establishes provenance, accessibility, time,
status, and conversation scope. It does not independently establish semantic
entailment between an arbitrary free-form statement and the referenced record;
providers must remain conservative until the Epistemic Critic gains that check.

## Phase gate

- `uv run pytest -q`: 76 passed.
- `uv run ruff check src tests migrations plugins`: passed.
- `uv run mypy`: passed for 80 source files.

Tests cover automatic reaction/suppressed records, missing-source rejection,
topic lifecycle, calculator activity evidence, owner authorization, exact
half-life decay, restart persistence, unsupported/fake/cross-conversation thought
claims, valid same-conversation thought evidence, continuity audit, and absence of
raw model reasoning from persistence.

## Deferred beyond Phase 4

- Thought retrieval/ranking and LLM-generated safe appraisal summaries.
- Versioned viewpoints and evidence-backed viewpoint-change claims.
- Independent semantic-entailment verification between claim text and evidence.
- UtteranceSession, SpeechUnit, interruption, cancellation, and re-planning.
- General activities, daily planning, journaling, sleep consolidation, and dream
  isolation remain Phase 8 work.
