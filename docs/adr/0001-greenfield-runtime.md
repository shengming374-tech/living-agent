# ADR 0001: Greenfield standalone runtime

- Status: Accepted
- Date: 2026-07-20

## Context

LivingAgent needs reliable work execution and continuous social behavior without
inheriting the compatibility and licensing constraints of a chat-focused bot.
MaiBot is GPL-3.0 and optimized around group-chat naturalness.

## Decision

Build an independent Python 3.12 runtime using FastAPI, Pydantic v2, SQLAlchemy
2, Alembic, asyncio, and SQLite/PostgreSQL-compatible models. MaiBot is a pinned,
ignored research checkout only. LivingAgent never imports it, requires its
service, or targets its internal interfaces. MCP is a future connector adapter,
not the native plugin protocol.

One persona has two internal cognitive views. Executive Cognition emits only
structured plans, capability proposals, evidence, and status. Social Cognition
alone renders user-visible language.

## Consequences

Mechanisms and runtime code must be re-derived and independently tested. MaiBot
code is not copied. Selected natural-language social Prompt excerpts may be reused
only with explicit provenance and license notices; they cannot change authority,
capability, memory, or execution contracts. Feature
parity is not a goal; security invariants take precedence over compatibility.
