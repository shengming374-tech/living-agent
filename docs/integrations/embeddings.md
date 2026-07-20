# Embedding model and API integration

LivingAgent has a host-owned embedding provider boundary with two implementations:

- `mock`: deterministic normalized feature hashing for tests and local development;
- `openai_compatible`: HTTP client for an OpenAI-compatible `/embeddings` API.

The embedding API is an explicit owner control-plane operation. It is not exposed
to the LLM, plugins, ordinary chat users, or automatic memory ingestion.

## Configure an OpenAI-compatible provider

Set the provider, API prefix, and exact model name:

```bash
export LIVING_AGENT_EMBEDDING_PROVIDER=openai_compatible
export LIVING_AGENT_EMBEDDING_MODEL='your-embedding-model'
export LIVING_AGENT_EMBEDDING_API_BASE_URL='https://api.example.com/v1'
export LIVING_AGENT_EMBEDDING_API_KEY='replace-with-provider-key'
```

If the model supports choosing its output width, configure it explicitly:

```bash
export LIVING_AGENT_EMBEDDING_DIMENSIONS=1536
```

When dimensions are configured, a response with any other width is rejected.
When omitted, the provider response determines the width, but every vector in a
batch must still have the same width.

Local OpenAI-compatible servers may use loopback HTTP:

```bash
export LIVING_AGENT_EMBEDDING_API_BASE_URL='http://127.0.0.1:11434/v1'
```

Remote plain HTTP is rejected unless
`LIVING_AGENT_EMBEDDING_ALLOW_INSECURE_HTTP=true` is explicitly set. HTTPS remains
the recommended remote transport. URLs containing credentials, a query, or a
fragment fail startup validation.

Available bounds:

```bash
export LIVING_AGENT_EMBEDDING_TIMEOUT_SECONDS=15
export LIVING_AGENT_EMBEDDING_MAX_BATCH_SIZE=32
export LIVING_AGENT_EMBEDDING_MAX_INPUT_CHARS=12000
export LIVING_AGENT_EMBEDDING_MAX_TOTAL_CHARS=48000
export LIVING_AGENT_EMBEDDING_MAX_RESPONSE_BYTES=4194304
```

## LivingAgent API

The development API uses the configured owner identity:

```bash
curl -sS http://127.0.0.1:8000/v1/embeddings/status \
  -H 'X-Actor-ID: owner-local'

curl -sS http://127.0.0.1:8000/v1/embeddings \
  -H 'X-Actor-ID: owner-local' \
  -H 'Content-Type: application/json' \
  --data '{"input":["first text","second text"]}'
```

`POST /v1/embeddings` returns an OpenAI-shaped list with ordered vector items,
plus the configured provider name and validated dimensions. The request cannot
override the configured model. Unknown fields and empty input are rejected.

`X-Actor-ID` is only a development control-plane mechanism. Production must put
these endpoints behind authenticated owner administration; a caller-controlled
header is not production authentication.

## Permission and data boundary

Embedding is classified as external data transfer. For every request, host code:

1. verifies owner authority;
2. applies batch, per-input, total-character, and response-byte limits;
3. creates one temporary grant for `model.embedding.generate` / `send`;
4. asks the Capability Broker to validate and consume that exact grant;
5. sends the batch only after the owner confirmation decision;
6. validates HTTP status, JSON shape, indexes, finite floats, and dimensions;
7. audits provider/model/count/character total/dimensions or a bounded error code.

Input text, vectors, the API key, Authorization header, and upstream error body
are not written to audit. Redirects and proxy environment inheritance are disabled
for the provider client. Non-success provider bodies are never surfaced through
the LivingAgent API.

## Current limitations

- The remote protocol is OpenAI-compatible Bearer authentication only. Provider-
  specific signing and nonstandard request formats need separate adapters.
- The status endpoint reports configuration and limits; it does not make a paid
  provider request.
- Embeddings are returned to the owner but are not persisted yet.
- Committed memories are not automatically sent to an embedding provider.
- Semantic/vector memory retrieval, index rebuilds, model migration, and
  PostgreSQL vector acceleration remain unimplemented.
- The Mock provider is deterministic test infrastructure, not a semantic model.

These limits preserve the existing rule that private or cross-session memory is
scope-filtered before any future ranking or external processing.
