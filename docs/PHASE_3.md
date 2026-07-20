# Phase 3 completion record

Completed on 2026-07-20 across the memory control commit and the
`feat(control): add persona and prompt version workflows` commit.

## Memory control

- Candidate observations persist separately and never auto-commit.
- Owner commit checks source existence, conversation/private/global scope,
  factuality, forbidden categories, and conflicts.
- External `verified` claims become `reported`; dreams remain `dream`.
- Core identity, owner/admin transfer, credentials, root/security policy, plugin
  authorization, privileged phrases, and role-play identities are rejected.
- Nodes support scoped search, optimistic edits, factuality/confidence changes,
  soft delete/restore, merge/split, source events, immutable history, and usage.

## Persona control

- Six deployed YAML layers: identity, values, traits, speech, boundaries, growth.
- Each layer has a strict Pydantic schema; unknown authority, secret, or prompt
  fields are rejected rather than becoming personality data.
- Workflow is edit/stage with diff, schema validation, full-pack test, deploy,
  immutable version history, recovery version, rollback, and audit.
- Stale stages cannot overwrite a newer deployment. Persona changes activate on
  restart and contribute the identity statement to the runtime root context.

## Prompt control

- Managed host, interaction, psyche, social, executive, speech, memory, and
  evaluation prompts with fixed paths and per-prompt variable allowlists.
- APIs provide content, token estimate, variable validation, diff, history,
  staging, automated render/security tests, deploy, rollback, and redacted render.
- Context preview uses the currently loaded Runtime policy, preserves typed source
  sections, and redacts structured and inline secret patterns.
- Root policy mutation requires owner authority plus a SHA-256-configured second
  factor. It creates a recovery version, must pass authority/broker/untrusted-data
  regression tests, and only activates after restart. Group chat has no mutation path.

## Phase gate

- `uv run pytest -q`: 65 passed with no warnings.
- `uv run ruff check src tests migrations plugins`: passed.
- `uv run mypy`: passed for 72 source files.

Tests cover memory pollution and cross-session leakage, every memory lifecycle
operation, invalid persona authority fields, stale deploys, premature deploys,
prompt variable/render validation, secret redaction, root second authentication,
unsafe root rejection, recovery/rollback, restart activation, and chat isolation.

## Deferred beyond Phase 3

- Automatic memory extraction and model-driven candidate generation.
- Semantic/vector ranking; memory search is currently scope-first substring search.
- Persistent psyche and ThoughtRecord, interruptible utterance sessions, general
  multi-step execution, Control Studio frontend, and dream/activity systems.
