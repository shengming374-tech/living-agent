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
| `prompts/zh-CN/maisaka_replyer.prompt` | Colloquial visible-response objective; prompt text was not copied |
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

## Code and prompt borrowing declaration

No MaiBot source code, prompt text, schemas, names, or directory layout has been
copied into LivingAgent. No line-by-line translation was performed. The reports
record mechanism-level observations only; all implementation is greenfield under
LivingAgent's own typed contracts and tests. Therefore the current LivingAgent
source does not incorporate GPL-covered MaiBot code. Any future borrowing must be
recorded here before inclusion and reviewed for license consequences.
