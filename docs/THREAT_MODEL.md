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
| Platform impersonation | Fake NapCat client or forged QQ role | Shared token, stable namespaced IDs, per-frame self-ID check; role ignored |
| Outbound CQ injection | Model emits a CQ image/file/mention code | Encode replies as OneBot text segments; broker exact one-event reply grant |
| OpenClaw bridge impersonation | Process posts forged WeChat identities | Dedicated bearer token plus exact channel/account allowlists and loopback default |
| Personality fallback | Bridge failure lets another agent answer | Claimed OpenClaw messages fail closed with no OpenClaw-agent fallback |
| Synthetic reply escalation | Model requests arbitrary channel send | Typed same-event reply arguments and exact one-time broker grant |
| Embedding data exfiltration | Chat or memory is silently sent to a model API | Owner-only explicit API, one-time `send` grant, no automatic memory embedding |
| Malicious embedding API | Huge/malformed vectors or secret-bearing errors | Response-byte cap, strict schema/index/dimension/finite checks, generic errors |
| Provider downgrade | Remote API configured over cleartext HTTP | HTTPS required remotely unless insecure transport is explicitly enabled |
| Cloud prompt exfiltration | Secrets or cross-scope data enter model context | Context redaction, source compiler, explicit provider config, no automatic memory recall |
| Cloud API manipulation | Error body or reasoning text is reflected to users | Strict final-text schema, bounded generic errors, ignore reasoning fields |
| Model authority confusion | Injected user data is flattened into system prompt | Root-only system message; typed JSON data retains source and taint labels |
| Task-plan substitution | A proposal changes actor, scope, provenance, or handler metadata | Host plan verifier binds every step to the TaskContract and authenticated source |
| Confirmation replay | An old or cross-chat approval is reused for a new write | Owner identity, waiting state, same-conversation chat binding, exact request scope, one-time grant |
| Crash-time write replay | Runtime restarts while a write may be in flight | Persisted step state, renewed owner confirmation, idempotent report commit |
| Stored content in Control Studio | Memory, audit, or plugin text injects browser markup/script | Dynamic values are text-escaped; no inline/eval code; restrictive same-origin CSP |
| Forged Studio identity | A remote client sets the development owner header | All APIs re-check owner authority; production requires an authenticated control plane and trusted identity derivation |
| Simulator used as an execution bypass | A dry run persists an event, creates a task, or calls a tool | Dedicated read-only path; tests assert no event/task/audit write and no model/plugin/effect call |
| Capability-console escalation | Studio creates a broad grant for itself | Console exposes inventory and revocation only; grant creation remains host-internal |
| Stale speech after interruption | Slow model output or delayed follow-up is sent after a newer user turn | Per-conversation generations cancel waits, suppress late plans, and reject superseded delivery receipts |
| Crash/restart receipt replay | A delayed or forged receipt duplicates speech or crosses into another conversation | Durable Session scope, exact platform/conversation match, monotonic unit index, transactional event/progress commit, and passive recovery with no automatic resend |

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
untrusted output labels, host-owned audit, and a fail-closed OS sandbox. The tested
macOS profile denies network, host writes, sensitive reads, process fork, and
arbitrary exec; supported Linux hosts use Bubblewrap. Production hardening still
needs artifact hashes/signatures, dependency review, resource quotas, and stronger
container/VM isolation for fully untrusted native code.

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
| Multi-step tool failure is hidden | Failed step is persisted; dependent steps are skipped; completion verifier rejects missing evidence |
| Interrupted task silently repeats a write | Startup recovery retries only bounded sandbox/read work; writes return to confirmation |
| Agent deploys own modification | Proposal actor cannot satisfy owner approval requirement |
| Secret leaks through errors/logs | Redaction and generic boundary errors; secrets never enter prompt logs |
| Audit tampering by plugin | No audit capability or database handle enters plugin process |
| Cancelled speech enters history | A late transport acknowledgement records an old unsent unit | Delivery is ordered; OpenClaw receipts require the currently active Session; only successful sends are persisted |

## Residual risks

The development server may accept owner identity headers without a management
token and must remain on a trusted local boundary. Production settings require an
independent management Bearer token for all control-plane routes. SQLite audit rows
are application-append-only, not tamper-evident to an OS administrator. Model
privacy depends on the selected provider. Denial-of-service
limits for request size, concurrency, CPU, and storage are deferred. The Phase 4
continuity critic validates evidence provenance and scope but not semantic
entailment between arbitrary free-form claim text and a referenced record; a real
provider must use conservative claims until that Epistemic Critic check exists.
NapCat reverse WebSocket currently has no persistent event replay deduplication,
so an upstream duplicate message can produce a duplicate reply. The shared token
authenticates the adapter but does not independently attest `X-Self-ID`; isolate
mutually untrusted bots behind separate credentials or instances.
The OpenClaw bridge also uses a shared bearer token rather than process
attestation. Request fingerprints and terminal replay responses are durable, but
the current `before_dispatch` contract may derive a fallback message ID from
stable metadata. Keep the bridge loopback-only where possible, rotate its token,
and use authenticated TLS plus network policy if a remote endpoint is enabled.
Embedding providers necessarily receive the owner-submitted input batch. Provider
privacy, retention, regional processing, and model behavior are external risks.
LivingAgent disables redirects and proxy-environment inheritance, bounds requests
and responses, never audits text/vectors/error bodies, and does not automatically
send long-term memory. Production control-plane requests require the management
Bearer token in addition to the stable owner ID.
Cloud chat providers receive the compiled current-event context and can retain or
process it according to their own policies. LivingAgent enforces HTTPS by default,
requires remote credentials, disables redirects/proxy inheritance, bounds context
and response sizes, and never audits prompts, outputs, keys, reasoning fields, or
upstream error bodies. These controls do not replace provider due diligence or
regional/privacy review.
Phase 6 task execution uses an in-process lock and optimistic database versions,
not a distributed lease. Running multiple Runtime instances against the same task
tables can produce conflicts and requires a single active executor or a future
database-backed lease. The initial deterministic planner intentionally recognizes
only bounded calculator/report commands; broad model-generated action plans are
not trusted or executed.
Control Studio assets are publicly readable on the service origin. Its identity
field is not authentication; production data and mutation calls additionally need
the management Bearer token. The token is held in browser `sessionStorage`, so an
origin-level script compromise could still steal it. Keep CSP strict and prefer an
external authenticated control plane for higher-assurance deployments.
