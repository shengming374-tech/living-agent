# Phase 7: Control Studio

Completed on 2026-07-21.

## Delivered

- Bundled same-origin Studio at `/studio`, included in the installable wheel and
  protected by CSP, no-sniff, no-referrer, and no-store browser headers.
- Overview, Memory Explorer, Persona Editor, Prompt Lab, Plugin Center,
  Capability Manager, Task Console, User Directory, Audit Log, Version History,
  and Behavior Simulator views.
- Owner-only memory-candidate listing with status filtering.
- Capability definition and active-grant inventory plus audited grant revocation.
- Side-effect-free simulation of trust normalization, conversation momentum,
  `TurnDecision`, typed context sections, and bounded executive task proposals.
- Human-readable API validation errors and responsive desktop/mobile layouts.

## Security boundaries

- Studio never creates a capability grant and every data API independently checks
  the configured stable owner identity.
- Root Prompt staging, deployment, and rollback still require a fresh second
  factor. The password value is held only for the current request and is not saved
  in browser storage.
- Simulator returns before all persistence and effect paths. It does not call the
  LLM, plugin worker, platform adapter, audit service, or task repository.
- Memory and audit content is escaped before DOM insertion. Studio JavaScript has
  no inline handlers, dynamic code evaluation, or external dependencies.
- `X-Actor-ID` remains a development identity selector. Production requires an
  independent management Bearer token; Studio stores it only in `sessionStorage`
  and attaches it to control-plane API requests.

## Verification

- Full Python suite: `175 passed`.
- Ruff: passed. Strict mypy: passed across 112 source files.
- OpenClaw bridge regression suite: `13 passed`.
- Pytest covers asset headers and routing, owner denial, memory inventory,
  capability listing/revocation audit, side-effect-free task simulation, and
  injection containment.
- Ruff and strict mypy cover the Python implementation; Node syntax checking
  covers the browser script.
- Headless Chromium exercised all eleven views, the simulator submission, and the
  wrong-owner error state at 1440x960.
- Chromium mobile checks at 390x844 exercised Overview, Memory, Persona, Prompt,
  Task, and Simulator views with no document-level horizontal overflow.
- A built wheel was inspected to confirm all three Studio assets are packaged.

## Deferred

- Multi-factor or external identity-provider login beyond the production Bearer
  credential.
- Multi-user management roles beyond the configured owner boundary.
- Persistent Studio preferences beyond the non-secret development actor ID.
- Multimodal inspection, which remains scheduled for version `0.2.0`.
- Phase 8 journaling, sleep, dreams, daily activities, and self-change proposals.
