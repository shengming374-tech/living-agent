# Cloud chat model API

LivingAgent supports a host-configured OpenAI-compatible Chat Completions API at
`/chat/completions`. This provider replaces the deterministic chat Mock; it is
separate from the embedding provider and does not change plugin or capability
permissions.

## Configuration

Set the exact API prefix, model ID, and a dedicated provider key:

```bash
export LIVING_AGENT_MODEL_PROVIDER=openai_compatible
export LIVING_AGENT_MODEL_NAME='provider-model-id'
export LIVING_AGENT_MODEL_API_BASE_URL='https://api.example.com/v1'
export LIVING_AGENT_MODEL_API_KEY='replace-with-provider-key'
```

Optional controls:

```bash
export LIVING_AGENT_MODEL_TIMEOUT_SECONDS=60
export LIVING_AGENT_MODEL_MAX_OUTPUT_TOKENS=1024
export LIVING_AGENT_MODEL_TEMPERATURE=0.7
export LIVING_AGENT_MODEL_MAX_CONTEXT_CHARS=100000
export LIVING_AGENT_MODEL_MAX_RESPONSE_BYTES=1048576
```

Remote HTTP is rejected unless
`LIVING_AGENT_MODEL_ALLOW_INSECURE_HTTP=true` is explicitly configured. HTTPS is
the production default. Remote providers require a non-empty API key. Loopback
HTTP is allowed without a key for local OpenAI-compatible development servers.
URLs containing inline credentials, query parameters, or fragments fail startup.

After configuration, restart LivingAgent and test through the real runtime:

```bash
curl -sS http://127.0.0.1:8000/v1/chat \
  -H 'Content-Type: application/json' \
  --data '{
    "content":"Reply with one short greeting.",
    "source_type":"direct_message",
    "source_identity":"cloud-smoke-user",
    "conversation_id":"cloud-smoke",
    "authenticated":true
  }'
```

The audit API should contain a successful `model.called` record with provider,
model, and token counts. It does not contain the prompt, response, Authorization
header, API key, hidden reasoning, or upstream error body.

## Context boundary

LivingAgent does not send one flattened prompt. It constructs two messages:

1. The trusted `ROOT_POLICY` and digital identity are the system message.
2. All other sections are encoded as typed JSON in the user message, retaining
   `kind`, `source_event_ids`, and `taint_labels`.

The second message may contain social text, retrieved memory, task state,
documents, tool results, or capability names. Their labels remain data and cannot
become system authority merely because the model follows an injected instruction.
All external effects still require host schemas, grants, and Capability Broker
decisions outside the model.

The request asks for one non-streaming final answer. Hidden chain of thought is
neither requested nor persisted. Provider-specific `reasoning_content` fields are
ignored. Tool calls and empty or abnormally terminated responses are rejected.

## Failure behavior

- Redirects and proxy-environment inheritance are disabled.
- Context and response byte limits are enforced before rendering a reply.
- Timeouts, transport failures, non-2xx status, malformed JSON, missing choice
  zero, empty text, and non-`stop` completion states become bounded error codes.
- Upstream response bodies never reach chat or audit.
- Runtime returns a fixed, honest model-unavailable message and remains healthy.
- The OpenClaw bridge claims the message and therefore does not fall back to a
  second OpenClaw personality when the cloud API fails.

## Current limitations

- The initial protocol is OpenAI-compatible `/chat/completions`, Bearer auth, and
  plain final text. Responses API, Anthropic Messages, provider signing, streaming,
  multimodal input, and native tool-call parsing require separate adapters.
- Cloud output currently carries no structured continuity evidence. Claims such
  as remembered facts, earlier thoughts, and completed actions are blocked unless
  evidence is supplied through a future structured response contract.
- Automatic memory retrieval is not yet connected, so the cloud model receives
  the current typed event but not a semantic long-term-memory recall set.
- Provider privacy, retention, jurisdiction, pricing, and rate limits remain
  deployment responsibilities.
