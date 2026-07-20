# ADR 0002: Policy and effects stay outside the model

- Status: Accepted
- Date: 2026-07-20

## Context

All text visible to a model can contain adversarial instructions. Prompt-only
controls cannot reliably distinguish intent from data or enforce side effects.

## Decision

Normalize ingress as a source-aware `TrustedEvent`. Compile typed context
sections instead of concatenating sources. Treat model actions as proposals.
Every effect crosses a deterministic `CapabilityBroker` that evaluates actor,
authority, session, declared grant, argument schema, taint, operation class,
resource scope, and confirmation. Audit all decisions before execution.

Plugins receive request data and a temporary grant, never the agent object,
database handle, raw environment, chat history, or long-term memory. Free-text
plugin output re-enters as untrusted data.

## Consequences

The application remains secure under the narrower goal that model compromise
does not equal permission compromise. Policy rules are explicit and testable,
at the cost of additional schemas and broker plumbing for every new capability.
