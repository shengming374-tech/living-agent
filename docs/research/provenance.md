# Research provenance

## Reference identity

- Repository: `https://github.com/Mai-with-u/MaiBot.git`
- Revision: `73ef023c9c739af5e65a44361489b48ab7a5ed23`
- Branch at inspection: `main`
- Inspection date: 2026-07-20
- License found in reference: GNU GPL version 3
- Local checkout: `references/maibot/` (ignored, read-only research material)

## Files inspected and mechanism learned

| Reference file | Research purpose |
| --- | --- |
| `README.md`, `LICENSE` | Project intent and licensing boundary |
| `src/maisaka/turn_gates.py` | Reply necessity, frequency, idle compensation, silence invariant |
| `src/maisaka/reply_necessity.py` | Participation signals and recent-presence penalty |
| `src/maisaka/attention_drift.py` | Context-anchored association rather than random distraction |
| `src/maisaka/reasoning_engine.py` | Interruptible planning and tool stage separation |
| `src/maisaka/chat_loop_service.py` | Planner context/tool loop and hook placement |
| `src/chat/replyer/replyer_manager.py` | Per-session reply generator ownership |
| `src/chat/replyer/maisaka_generator.py` | Dedicated reply-generation layer |
| `src/chat/replyer/maisaka_generator_base.py` | Reply-only output boundary and real-history filtering |
| `prompts/zh-CN/maisaka_replyer.prompt` | Colloquial visible-response objective; selected prompt text is now copied with attribution |
| `src/config/official_configs.py` | `reply_style`, group-chat, and private-chat prompt string values only; no Python implementation copied |
| `src/chat/replyer/maisaka_generator_base.py` | Final visible-output instruction string only; no generator code copied |
| `src/chat/utils/utils.py` | Bounded post-generation message-count concept; algorithm was not copied |
| `src/maisaka/builtin_tool/reply.py` | Planner-to-expression handoff and segmented send concept |
| `src/maisaka/memory/mid_term.py` | Compact summaries and recall cues |
| `src/maisaka/memory/heuristic_injector.py` | Scoped, rate-limited memory recall |
| `src/services/memory_flow_service.py` | Evidence selection for person-fact writeback |
| `src/core/tooling.py` | Typed tool specifications, invocations, and results |
| `src/plugin_runtime/protocol/envelope.py` | Typed RPC envelope concepts |
| `src/plugin_runtime/host/rpc_server.py` | Host-enforced RPC timeout |
| `src/plugin_runtime/host/supervisor.py` | Runner lifecycle and terminate/kill escalation |
| `src/plugin_runtime/runner/runner_main.py` | Separate plugin runner responsibilities |

## Borrowing declaration

No MaiBot Python/JavaScript source code, schemas, runtime names, or directory
layout has been copied into LivingAgent. No code was translated line by line.
LivingAgent's runtime remains greenfield under its own typed contracts and tests.

The owner explicitly authorized direct Prompt reuse on 2026-07-21. The following
Chinese natural-language Prompt excerpts are copied into
`prompts/social/reply.txt`:

- the instruction to read prior chat, understand the current topic, and reply in
  an everyday colloquial way;
- the default plain, short, non-ornate reply-style paragraph;
- the short, single-topic group-chat attention rules and participation-frequency
  wording;
- the short private-chat attention rules;
- the instruction to output only visible speech without wrappers or mentions.

These excerpts came from `prompts/zh-CN/maisaka_replyer.prompt` and Prompt string
values embedded in `src/config/official_configs.py` and
`src/chat/replyer/maisaka_generator_base.py` at the pinned revision above. Only
the natural-language strings were copied; none of the surrounding Python control
flow was copied.

MaiBot is GPL-3.0. The copied Prompt excerpts remain subject to that license and
are identified in `THIRD_PARTY_NOTICES.md`; a copy of GPL-3.0 is distributed at
`LICENSES/MaiBot-GPL-3.0.txt`. This provenance record makes no claim that Prompt
text is outside copyright merely because it is not executable code.
