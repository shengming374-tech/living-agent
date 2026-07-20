# LivingAgent

LivingAgent is a greenfield runtime for a persistent digital persona with natural
social participation and reliable, policy-controlled task execution. It is not a
claim of consciousness and does not fabricate a biological body or life history.

The project currently starts with the trust and execution foundation. Long-term
memory, psyche state, interruptible speech, and management UI are staged features
and are listed explicitly as unimplemented until their tested slices land.

## Goals

- One externally consistent persona with separate social and executive cognition.
- Source-aware events and context instead of flattening all text into instructions.
- Code-enforced capability decisions outside the language model.
- Auditable tasks, evidence, memory provenance, and state changes.
- Native least-privilege plugins isolated from the main runtime.

## Non-goals

- Simulating biological embodiment or claiming real consciousness.
- Forking, wrapping, importing, or requiring MaiBot.
- Using MaiBot or MCP as the personality frontend or native plugin runtime.
- Arbitrary shell execution, agent-approved self-deployment, or chat-based policy edits.

## Architecture

```text
Platform/API input
      |
      v
Trust Boundary -> TrustedEvent -> Turn Gate
      |                              |
      |                     Social Cognition
      |                              |
      +-> typed Context Compiler <- structured Executive result
                                     |
                              Action Proposal
                                     |
                              Policy Engine
                                     |
                           Capability Broker
                          / deny ask allow \
                         v                 v
                 host capability    plugin subprocess
                         \                 /
                          verified evidence
                                  |
                         Social Cognition -> user

All decisions/effects ---------------------> Audit Log
```

Executive Cognition never sends natural-language messages. It returns structured
results that Social Cognition may express in the persona's voice.

## Development

Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) are recommended.

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run mypy
```

Run the development API from the project directory:

```bash
uv run uvicorn --app-dir src living_agent.app:app --reload
```

Then request `GET /health` or submit an authenticated-adapter envelope to
`POST /v1/chat`. Configuration defaults live in `config/default.yaml`; copy
`.env.example` values into the process environment for deployment overrides.

## Model configuration

Phase 1 uses a deterministic `MockLLMProvider`, requiring no credentials. A real
provider will implement the same protocol and receive only redacted, typed context.
Secrets belong in environment-backed settings and must never appear in prompt or
audit previews.

## Native plugins

The native host discovers strict manifests and invokes each plugin call in a new
isolated Python subprocess using JSON-RPC over stdio. Plugins receive no Agent,
database, chat-history, memory, prompt, persona, or host environment object. Every
invocation carries a temporary, minimal capability grant, and plugin output is
tainted as untrusted until independently verified. MCP may later be implemented as
an optional connector adapter; it is not a core dependency.

The calculator at `plugins/examples/calculator/` is the reference implementation.
To add a reviewed plugin:

1. Add `plugins/examples/<plugin>/manifest.yaml` and the declared entrypoint module.
2. Declare each operation's capability, broker operation, exact resource scope,
   input schema, output schema, hooks, background tasks, and data policy.
3. Expose one `invoke(params) -> dict` function. Do not import LivingAgent or expect
   host objects, secrets, installation hooks, or shell access.
4. Register host-owned Pydantic argument/output validation and policy for any new
   capability. A manifest declaration alone never creates a grant.
5. Add crash, timeout, schema, permission, taint, and verifier tests, then enable it
   as the owner through `POST /v1/plugins/{id}/enable`.

`GET /v1/plugins` lists discovery and enabled state. These management endpoints use
the development owner header described under security limitations.

## Permission model and prompt injection

Authenticated adapter identity, never a nickname or message claim, determines
authority. Language-model output is an action proposal only. The capability
broker checks actor, session, declared grant, arguments, scope, taint, write/send
intent, confirmation, and cross-session access before execution.

LivingAgent does not promise to recognize every prompt injection. It is designed
so malicious social text, documents, memories, and tool/plugin results cannot by
themselves grant permission or cross a data boundary. See
[`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

## Memory design

Planned memory nodes carry type, content, subject, source event IDs and trust,
factuality, confidence, importance, scope, timestamps, status, and version.
External observations pass candidate validation, factuality classification, and
conflict checks before commit. Authority, credentials, policies, plugin approval,
dream facts, and role-play identities can never auto-enter core memory.

## Persona and prompt changes

Persona will be layered across identity, values, traits, speech, boundaries, and
growth files. Persona and normal prompt changes follow edit, diff, validate,
stage, test, deploy, and audit. Root-policy changes additionally require a local
or high-authority identity, second authentication, a recovery point, security
regression tests, and restart activation. An agent may submit a patch proposal
but cannot approve or deploy it.

## Reference boundary

MaiBot is used only as read-only mechanism research. It is not a dependency and
does not run with LivingAgent. The exact GPL-3.0 reference revision and inspected
files are recorded in [`docs/research/provenance.md`](docs/research/provenance.md);
no code or prompts were borrowed.

## Implementation status

Implemented: Phase 0 research and architecture; Phase 1 secure runtime; and the
Phase 2 native plugin slice. The latter includes manifest discovery, owner enable
state, isolated per-call subprocesses, JSON-RPC, timeout/crash handling, one-time
broker grants, Calculator, structured task contracts, independent result
verification, social reporting, and audit evidence.

Not yet implemented: managed long-term memory, persistent psyche, utterance
interruption, general multi-step executive planning, Control Studio, arbitrary
third-party plugin installation, and dream/activity features. This section is
updated only after executable, tested vertical slices land.

## Security limitations

HTTP authentication, OS-level plugin sandboxing, tamper-evident audit storage,
provider privacy guarantees, resource quotas, and production deployment hardening
are not supplied by the current runtime. `/v1/chat` is an adapter ingress and its
`authenticated` identity flag is only trustworthy behind an authenticated adapter
or gateway. The development `X-Actor-ID` audit header is not production-grade
authentication. Never run unreviewed plugin code merely because process isolation
exists. The subprocess boundary minimizes data and contains crashes/timeouts, but
it is not an OS sandbox against hostile Python file or network syscalls; production
third-party plugins require a container, platform sandbox, or VM.
