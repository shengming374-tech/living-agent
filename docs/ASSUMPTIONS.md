# Engineering assumptions

1. The repository is greenfield and has no compatibility contract with MaiBot.
2. Python 3.12 is provisioned by `uv`; the host's system Python need not be upgraded.
3. Development uses SQLite through SQLAlchemy asyncio. Models avoid SQLite-only
   types so a PostgreSQL URL can replace it later.
4. A platform adapter authenticates `source_identity`. Display names and message
   content never establish identity or authority.
5. The first runtime has one configured owner ID and treats all other identities
   as members unless an authenticated adapter supplies a stronger mapping.
6. The Phase 1 model provider is deterministic and local. Real model credentials
   are deliberately deferred behind the same provider protocol.
7. Plugin calls combine one-shot subprocesses, a minimal environment, brokered
   grants, and an OS sandbox. macOS uses a tested `sandbox-exec` profile; supported
   Linux hosts use Bubblewrap. Production requires a detected backend and fails
   closed otherwise. Native-code review and resource isolation still require
   stronger container or VM controls for fully untrusted plugins.
8. `references/maibot/` is deliberately ignored by the main repository. Research
   provenance pins the inspected upstream revision without vendoring GPL code.
9. Phase 5 supports one-unit reactions and configurable one-to-three-unit engaged
   replies. A Runtime-owned coordinator invalidates stale generations across Chat
   API, NapCat, and OpenClaw. Replanning means producing a fresh response from the
   newer inbound event and current conversation state; cancelled old units are
   never mechanically resumed or rewritten in place.
10. Root prompt mutation is disabled when
    `LIVING_AGENT_ROOT_PROMPT_SECOND_FACTOR_SHA256` is unset. Only the digest is
    configured; the raw second factor is supplied per privileged request.
11. Managed Persona and Prompt files are single-process resources. The repository
    prevents stale-version deployment, but multi-instance production deployment
    also needs an external deployment lock or single control-plane writer.
12. Phase 4 has one `primary` PsycheState for the single LivingAgent persona.
    Thought and activity evidence remains source-bound, and continuity claims may
    only use evidence whose source events belong to the active conversation.
13. Psyche state and ThoughtRecord inspection/mutation are owner control-plane
    operations. `X-Actor-ID` is sufficient only in development and tests;
    production additionally requires the configured management Bearer token.
14. NapCat integration uses OneBot 11 reverse WebSocket because it supports event
    ingress and correlated API replies on one authenticated connection. QQ actor
    and conversation IDs are namespaced by bot `self_id`; nickname, group card,
    and group role remain untrusted display metadata.
15. A LivingAgent-generated reply to the same authenticated source event is an
    allowed system `reply`, not an unsolicited third-party `send`. It still needs
    an exact, one-time Capability Grant. Unsolicited and cross-conversation sends
    remain unimplemented.
16. The OpenClaw integration uses the typed `before_dispatch` hook available in
    OpenClaw 2026.6.10. OpenClaw owns WeChat login and delivery only; LivingAgent
    remains the sole personality, cognition runtime, memory owner, and capability
    authority. Claimed messages never fall back to the OpenClaw agent.
17. OpenClaw stores a keyed request fingerprint and terminal replay response before
    returning a reply. Completed requests replay without visible messages after
    restart. A prior invocation left processing/failed is not retried under the
    same message ID, because avoiding duplicate effects takes precedence over an
    automatic retry.
18. Direct WeChat text is the initial compatibility target. Group chat, media,
    proactive sends, and alternate OpenClaw channels remain denied or unclaimed.
    OpenClaw channels that omit typed sender/conversation IDs use a stable opaque
    hash of authenticated channel/account/session routing as the direct identity;
    missing all stable identity inputs remains a hard rejection.
19. Embedding generation is initially an explicit owner control-plane operation.
    It never automatically exports chat history or committed memories. Remote
    calls are external sends requiring a one-time broker grant and owner
    confirmation; audit stores only bounded operational metadata.
20. `openai_compatible` means the JSON `POST /embeddings` contract with optional
    Bearer authentication. Provider-specific authentication and payload variants
    require separate adapters rather than weakening response validation.
21. The first cloud chat adapter targets OpenAI-compatible non-streaming
    `/chat/completions`. The owner-selected endpoint/model/key are deployment
    configuration and cannot be changed by chat, model output, or plugins.
22. Cloud chat receives the trusted root as system content and all remaining
    context as typed, taint-labelled user data. Provider-specific reasoning fields
    are discarded; structured continuity evidence remains future work.
23. The owner has stated that the deployed WeChat participants already know the
    persona is AI. The default deployment persona therefore identifies herself as
    凤笑梦, understood as a non-biological digital persona constituted by AI, and
    does not repeat AI-disclosure boilerplate in ordinary conversation.
24. Short-term conversational continuity uses only a bounded, same-conversation
    window of persisted user and Agent turns. It is typed model context, not an
    automatic permanent-memory commit. Long-term recall reads only committed,
    scope-accessible reality memories and uses local lexical ranking; it never
    turns the current message into a permanent memory.
25. Speaking frequency is deterministic. Direct messages and explicit mentions
    stay responsive; optional unmentioned group participation requires a configured
    consecutive-user-turn threshold and cooldown, then emits one short reaction.
    Random reply probabilities are not used.
26. In-flight `UtteranceSession` state is durable, but recovery is passive: startup
    restores authorization and delivery progress without resending old text.
    OpenClaw may finish an already-issued Session with authenticated, exact-scope,
    in-order receipts. NapCat and Chat API Sessions wait for a new inbound turn,
    which cancels the stale remainder, because those transports have no durable
    post-restart receipt channel.
27. User auto-registration accepts only authenticated direct/group events and keys
    profiles by stable platform identity. Display names are mutable metadata and
    never establish owner/admin authority. Registration does not grant memory,
    prompt, plugin, or capability access.
28. Multimodal understanding is deferred to version `0.2.0`. Until then, image,
    audio, video, voice, and file segments may be represented as transport
    placeholders but are never claimed as parsed or understood content.
29. Phase 6 task understanding uses an explicit deterministic grammar for bounded
    calculations, task-report requests, and confirmation commands. This keeps
    actions testable and prevents model prose from becoming authority. Arbitrary
    natural-language planning requires later typed model-proposal adapters and a
    broader independently verified action catalog.
30. Task runs and step evidence persist in the primary database. Single-process
    execution uses an in-process lock plus optimistic row versions; multi-instance
    production requires a distributed task lease. Startup may retry interrupted
    sandbox/read steps, but an interrupted write always returns to owner
    confirmation before any effect is attempted again.
31. Control Studio is served from the same FastAPI origin and uses the existing
    owner APIs. Its `X-Actor-ID` selector is convenient for local development;
    production also requires the management Bearer token, retained only for the
    current browser session. External identity-provider integration remains future
    deployment hardening.
32. Behavior simulation may read bounded, same-conversation history to reproduce
    momentum, but it performs no event, task, memory, or audit write and calls no
    model, plugin, or platform adapter. Its output is a deterministic preview, not
    permission to execute the previewed proposal.
33. An authenticated owner may inspect the complete memory inventory without a
    conversation header. Non-owner reads still apply global, stable private-actor,
    and exact conversation scope filters before search.
34. Production configuration requires a dedicated management API token of at least
    32 characters. All `/v1` control-plane routes require it; `/v1/chat` and
    `/v1/adapters/*` retain their separate platform/gateway authentication models.
