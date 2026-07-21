# Security hardening record

Completed on 2026-07-21 after the Phase 7 control-plane audit.

## Management authentication

- Production configuration requires a dedicated management API token with at
  least 32 characters and refuses to start without one.
- All `/v1` control-plane routes require `Authorization: Bearer <token>` before
  their existing stable Owner-ID checks run.
- `/v1/chat` and `/v1/adapters/*` remain separate ingress boundaries and retain
  their adapter/gateway authentication requirements.
- Rejected management authentication is audited with bounded reason codes; token
  values never enter audit details.
- Control Studio stores the token only in browser `sessionStorage` and exposes an
  authentication dialog on desktop and mobile.

## Plugin OS sandbox

- Every plugin call remains a one-shot isolated Python worker with minimal
  environment, bounded stdio, timeout, and process-group termination.
- On macOS, `sandbox-exec` additionally denies network access, all host writes,
  sensitive host reads, process fork, and arbitrary process execution. Tests
  exercise each denied operation against a probe plugin.
- Supported Linux deployments use Bubblewrap with an unshared network/process
  namespace, read-only host mount, hidden home directory, and private temporary
  storage.
- Production forces sandbox mode to `required`; no detected backend is a startup
  error. Development `auto` mode uses a backend when present.
- Native-code provenance, signatures, CPU/memory quotas, and container/VM
  isolation remain production supply-chain responsibilities.

## OpenClaw ingress idempotency

- The database stores a hash-keyed channel/account/message identity, request
  fingerprint, processing state, and a reply record with visible text removed.
- A completed request replays after restart without re-entering Runtime or
  emitting a second visible response.
- Reusing a message ID with different content is a conflict.
- A request interrupted while processing fails closed under the same message ID;
  it is not automatically retried because duplicate effects are more dangerous
  than requiring the sender to submit a new message.

## Verification

- Full Python suite: `188 passed`.
- Ruff: passed.
- Strict mypy: passed across 118 source files.
- OpenClaw Node bridge suite: `13 passed`.
- Studio and bridge JavaScript syntax checks: passed.
