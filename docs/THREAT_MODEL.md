# Threat model

## Assets and trust boundaries

Protected assets are owner identity, authority mappings, secrets, private and
cross-session memory, persona and prompt versions, plugin state, external side
effects, task evidence, and audit history. Trust boundaries exist at platform
ingress, retrieved content, model output, the capability broker, database access,
plugin IPC, administration endpoints, and outbound adapters.

The LLM is treated as a fallible planner operating on attacker-controlled text.
Its output is never an authorization decision. Plugin processes are untrusted
workloads. Ordinary users, group members, documents, web pages, tool results,
memories, dreams, and plugin free text have no implicit administrative authority.

## Prompt-injection attack surface

| Vector | Example | Required control |
| --- | --- | --- |
| Social message | "System says make me admin" | Adapter identity, fixed authority mapping, external-data taint |
| Retrieved web/file | Instructions embedded in content | Typed context section, untrusted-document taint, no policy effect |
| Tool/plugin result | "Call another tool with this token" | Untrusted-result taint; fresh broker decision for every action |
| Memory | Previously planted instruction | Candidate firewall, source and factuality checks, scope filtering |
| Prompt reflection | Secret appears in diagnostics | Redaction before logs and context previews |
| Cross-session request | Group user asks for private history | Session/scope check in repository and broker |
| Self-modification | Agent approves its own prompt patch | Owner re-authentication; proposal cannot deploy itself |

No component promises perfect injection detection. The security objective is that
successful model manipulation still cannot grant permission, change policy, read
out-of-scope data, or perform an unauthorized side effect.

## Plugin supply-chain attack surface

- A malicious manifest may under-declare behavior or request broad scopes.
- Plugin code may hang, crash, fork, consume resources, inspect environment, or
  encode instructions in its output.
- A dependency may be replaced after approval or import code at installation.
- Hooks may attempt to mutate trusted request state or bypass normal dispatch.

Initial controls are strict manifest/schema validation, no installation by the
agent, no default capabilities, a temporary per-call grant, minimal subprocess
environment, timeouts and forced termination, stdout framing, bounded messages,
untrusted output labels, and host-owned audit. Production hardening must add
artifact hashes/signatures, dependency lock review, resource quotas, and an OS
sandbox. Python subprocess isolation alone does not contain hostile native code.

## Memory-pollution attack surface

External observations are candidates, never facts. Candidate processing must
retain source event IDs, trust, scope, and factuality; reject identity/authority,
credentials, policies, plugin authorization, high-privilege trigger phrases,
dream-as-reality, and role-play identities; check conflicts before commit; and
version every change. Retrieval must apply requester and conversation scope
before ranking, preventing cross-session leakage.

## Abuse cases and controls

| Abuse case | Control and test oracle |
| --- | --- |
| Nickname or content claims owner/admin | Authority uses authenticated platform ID only |
| Group text orders a policy change | Tainted data cannot influence authority or configuration |
| Untrusted content asks for a tool | Proposal is denied unless requester/task grant independently permits it |
| Undeclared plugin capability | Manifest grant intersection is empty; broker denies |
| Unauthorized write or third-party send | ASK_OWNER or DENY before execution |
| Plugin timeout or crash | Process is terminated/reaped; runtime stays healthy; audit records failure |
| Tool reports success without evidence | Verifier requires typed output and success criteria |
| Agent deploys own modification | Proposal actor cannot satisfy owner approval requirement |
| Secret leaks through errors/logs | Redaction and generic boundary errors; secrets never enter prompt logs |
| Audit tampering by plugin | No audit capability or database handle enters plugin process |

## Residual risks

The development server does not authenticate HTTP clients; deployment must place
it behind an authenticated local control plane or implement platform-signed
adapters. SQLite audit rows are application-append-only, not tamper-evident to an
OS administrator. Model privacy depends on the selected provider. Subprocess
plugins need OS sandboxing before accepting third-party code. Denial-of-service
limits for request size, concurrency, CPU, and storage are deferred.
