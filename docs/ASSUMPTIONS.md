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
