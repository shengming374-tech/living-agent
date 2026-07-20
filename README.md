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

The runnable API and configuration commands will be added with Phase 1. The
current Phase 0 package verifies the tooling and architecture baseline only.

## Model configuration

Phase 1 uses a deterministic `MockLLMProvider`, requiring no credentials. A real
provider will implement the same protocol and receive only redacted, typed context.
Secrets belong in environment-backed settings and must never appear in prompt or
audit previews.

## Native plugins

The Phase 2 design uses a strict manifest and JSON-RPC to a separate Python
subprocess. Plugins receive no filesystem, network, chat-history, memory, send,
persona, prompt, or hook permission by default. Every invocation carries a
temporary, minimal capability grant. Plugin free text is untrusted data. MCP may
later be implemented as an optional connector adapter; it is not a core dependency.

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

Implemented: Phase 0 research, architecture decisions, threat model, packaging,
and quality-tool baseline.

Not yet implemented: runtime/API, persistence, plugins, managed memory, persistent
psyche, utterance interruption, general executive planning, Control Studio, and
dream/activity features. This section is updated only after executable, tested
vertical slices land.

## Security limitations

HTTP authentication, OS-level plugin sandboxing, tamper-evident audit storage,
provider privacy guarantees, resource quotas, and production deployment hardening
are not supplied by the Phase 0 baseline. Never run unreviewed plugin code merely
because process isolation exists.
