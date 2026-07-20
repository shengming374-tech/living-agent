# Why MaiBot mechanisms are insufficient for LivingAgent

This document evaluates fit for LivingAgent, not the overall quality of MaiBot.

## Goal mismatch

MaiBot's own README prioritizes lifelike group-chat presence over being a
feature-complete, efficient assistant. That yields strong social timing but is
not a sufficient contract for reliable work: task success criteria, evidence,
write confirmation, rollback, and epistemic verification need to be first-class
runtime objects rather than reply-planner conventions.

## Authority and trust need a separate kernel

MaiBot's planner, tools, history, hooks, and reply flow are deeply integrated.
LivingAgent requires an explicit invariant that text and model output can propose
but never grant. Authority must derive from authenticated platform IDs, while
documents, memories, and plugin output preserve source and taint across every
hop. Prompt instructions alone cannot enforce this boundary.

## Memory needs lifecycle and factuality controls

MaiBot contains useful session filters, evidence-oriented person-fact writeback,
and mid-term summaries. LivingAgent additionally needs candidate validation,
conflict handling, factuality (`verified/reported/inferred/imagined/dream/fictional`),
scope, versions, answer-use provenance, soft delete/restore, merge/split, and a
hard ban on memory-derived authority.

## Plugins need least privilege by construction

MaiBot's current plugin runtime is sophisticated but exposes a broad integrated
SDK and compatibility surface. LivingAgent begins with no file, network, history,
memory, send, persona, prompt, or hook permission; intersects each invocation
with a manifest; and gives a subprocess only minimized request data. The design
does not target MaiBot plugin compatibility.

## Human-like behavior cannot weaken execution

Attention drift, varied expression, and conversational presence are useful only
when anchored to real context. LivingAgent will not deliberately degrade tool
use, invent experiences, persist hidden chain of thought, or let social intimacy
raise authority. Natural reporting must remain traceable to audit and evidence.

## Architectural boundary

LivingAgent does not import MaiBot, run beside it, use it through MCP, wrap its
chat frontend, copy its directory structure, or depend on its models/prompts.
Social and executive cognition are new LivingAgent contracts around one persona.
