# Phase 2 completion record

Completed on 2026-07-20 in the `feat(plugins): add isolated calculator plugin` commit.

## Implemented

- Strict Pydantic manifest, capability, operation, JSON-RPC, request, response,
  `TaskContract`, executive proposal, plugin result, and verification schemas.
- Plugin discovery and runtime enable/disable state with owner checks and audit.
- One independent Python subprocess for every plugin invocation, `-I` isolated
  interpreter mode, explicit minimal environment, JSON-RPC over stdio, response
  size checks, timeout, cancellation cleanup, process-group termination, and
  generic errors that do not expose plugin stderr.
- Manifest permission intersection before the global capability broker; every
  successful call consumes a one-time, conversation-scoped grant.
- A standalone calculator plugin using a bounded AST interpreter with no `eval`,
  shell, host imports, network API, or storage API.
- Executive calculation detection, `TaskContract`, capability proposal,
  calculator executor, independent host arithmetic verifier, evidence record, and
  Social Cognition rendering of the verified result.
- Plugin inventory and enable/disable APIs. Arbitrary plugin invocation and agent
  installation are intentionally absent.

## Phase gate

- `uv run pytest -q`: 39 passed with no warnings.
- `uv run ruff check src tests migrations plugins`: passed.
- `uv run mypy`: passed for 53 source files.
- `uv build --wheel`: built `living_agent-0.1.0-py3-none-any.whl`.

Tests include manifest validation, discovery, RPC, input/output schema validation,
undeclared permissions, minimal environment, hostile output taint, timeout,
process crash, code-expression rejection, forged-success rejection, successful
chat execution, owner plugin controls, and tool/plugin/capability audit entries.

## Residual boundary

Python subprocess isolation is a failure and data-minimization boundary, not a
complete OS security boundary. Unreviewed Python can still attempt direct file or
network syscalls outside the broker. Production third-party plugins require a
container, seccomp/App Sandbox, restricted service account, or VM plus artifact
signing and resource quotas. The current example is repository-owned and reviewed.
