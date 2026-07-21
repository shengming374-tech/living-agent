# MaiBot mechanisms worth studying

Research revision: `73ef023c9c739af5e65a44361489b48ab7a5ed23`
(official `Mai-with-u/MaiBot`, inspected 2026-07-20).

## Participation before generation

`src/maisaka/turn_gates.py` and `src/maisaka/reply_necessity.py` gate planning on
mentions, direct requests, recent bot presence, effective reply frequency,
message pressure, and idle time. A notable invariant prevents silence alone from
triggering repeated replies. LivingAgent adopts the mechanism-level idea that a
turn is a graded participation decision, but replaces trigger/wait with a typed
`observe/react/engage/act` decision and explicit interruption tolerance.

## Planner and Replyer separation

`src/maisaka/reasoning_engine.py`, `src/maisaka/chat_loop_service.py`, and
`src/chat/replyer/` separate planning/tool choice from final expression. Planner
requests can be interrupted when new messages arrive. The reply tool carries a
reply guide and references into the reply generator. LivingAgent adopts the
separation and interruption principle, while enforcing a stronger contract:
Executive Cognition cannot send text and Social Cognition alone owns expression.

## Short reply shaping

`prompts/zh-CN/maisaka_replyer.prompt`,
`src/chat/replyer/maisaka_generator_base.py`, and
`src/chat/utils/utils.py` show a useful three-stage boundary: the Replyer reads
real chat history and produces only colloquial visible content; output rules
exclude analysis and wrappers; a separate post-processor bounds message length
and message count. LivingAgent independently implements the post-processing
algorithm and typed output boundary. Its social Prompt now directly reuses selected
natural-language style sentences under the recorded GPL-3.0 provenance.
Its `TurnDecision` chooses one short unit for `react` and two or three equally
short semantic units for `engage`; typed `UtteranceSession` data then crosses the
same-event platform grant.

## Conversation-presence signals

The turn gates measure the bot's recent share of a conversation rather than
replying to every message. `src/maisaka/attention_drift.py` constrains topic drift
to hooks in recent messages and explicitly avoids fake inefficiency. LivingAgent
uses conversation momentum, current focus, unresolved topics, and real activity
records; it will not copy drift prompts or simulate humanity with random errors.

## Layered memory recall

`src/maisaka/memory/mid_term.py` compacts old chat into recallable summaries,
while `src/maisaka/memory/heuristic_injector.py` creates an impression and searches
related memory with session/person filtering and cache limits. LivingAgent adopts
source-aware, scoped recall and separation of episodic summaries from person
facts. It adds a mandatory candidate firewall, factuality labels, provenance,
version history, and strict cross-session access checks.

## Plugin Host/Runner split

`src/plugin_runtime/host/supervisor.py`, `host/rpc_server.py`, `runner/runner_main.py`,
and `protocol/envelope.py` demonstrate a Host/Runner process boundary, typed RPC
envelopes, timeouts, health checks, termination/kill escalation, and capability
services. LivingAgent independently implements a smaller per-plugin JSON-RPC
stdio slice with temporary grants. It does not reuse MaiBot SDK contracts or code.

## Lessons retained

- Decide whether and how strongly to participate before generating speech.
- Make planning interruptible and discard stale reply plans.
- Keep every social message short; express a fuller response as a few semantic
  units rather than one long block or mechanical punctuation fragments.
- Track recent presence and conversation pace, not fixed response counts.
- Keep retrieved memory visibly distinct from current user messages.
- Isolate plugin failure and make timeouts host-enforced.
