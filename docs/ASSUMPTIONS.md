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
7. The Phase 2 plugin sandbox is process isolation plus a minimal environment and
   brokered capability grant. It is not an OS security boundary against hostile
   native code; production requires containers, seccomp/App Sandbox, or a VM.
8. `references/maibot/` is deliberately ignored by the main repository. Research
   provenance pins the inspected upstream revision without vendoring GPL code.
9. Early chat responses are single units. Utterance sessions, interruption, and
   dynamic multi-unit speech remain Phase 5 work and are not implied by the API.
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
    operations. `X-Actor-ID` is sufficient only in development and tests; a
    production deployment must authenticate those HTTP requests externally.
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
17. OpenClaw bridge replay suppression is deliberately in-memory for the first
    vertical slice. A LivingAgent restart clears it, so upstream retries after a
    restart may produce a second response until persistent event keys are added.
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
    automatic permanent-memory commit; semantic memory recall remains explicit.
