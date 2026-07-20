# Phase 3 partial completion record

Memory control was completed on 2026-07-20 in the
`feat(memory): add candidate firewall and control API` commit. Phase 3 as a whole
remains incomplete because persona and prompt versioning APIs are not implemented.

## Implemented memory scope

- Candidate observations are persisted separately and never auto-commit.
- Owner commit passes source existence, conversation scope, private identity,
  global-owner source, factuality, forbidden-category, and conflict checks.
- External claims requesting `verified` are stored as `reported`; dreams stay
  `dream` and do not become reality facts.
- Core identity, owner/admin transfer, credentials, security/root policy, plugin
  authorization, privileged trigger phrases, and role-play identities are rejected.
- Nodes contain the required type, content, subject, source IDs/trust, factuality,
  confidence, importance, scope, timestamps, status, and version fields.
- APIs support scoped view/search, modification with optimistic version checks,
  factuality/confidence changes, soft delete, restore, merge, split, source events,
  version history, and response usage history.
- Every candidate decision and node mutation is recorded in the host-owned audit.

## Phase gate at this checkpoint

- `uv run pytest -q`: 53 passed with no warnings.
- `uv run ruff check src tests migrations plugins`: passed.
- `uv run mypy`: passed for 60 source files.

The new security tests prove that ordinary messages do not directly create memory,
pollution categories are rejected, missing or cross-conversation sources fail,
private memory does not leak to another member, and conversation memory does not
leak to another conversation.

## Not implemented in Phase 3

- Persona layered files, schemas, edit/diff/stage/test/deploy/rollback API.
- Prompt Lab, token estimates, variable validation, render tests, recovery points,
  root-prompt second authentication, restart activation, and context preview API.
- Automatic memory extraction or model-driven candidate creation.
- Semantic/vector ranking. Current search is scope-first substring search.
