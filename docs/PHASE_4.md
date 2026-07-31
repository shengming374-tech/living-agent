# 阶段 4 完成记录 / Phase 4 Completion Record

于 2026-07-20 在提交 `feat(psyche): add persistent thought and continuity evidence` 中完成。

## 持久心理状态

- Alembic 修订 `0004_persistent_psyche` 使用兼容 PostgreSQL 的 SQLAlchemy 类型创建 PsycheState、ThoughtRecord、未解决话题和活动表。
- 单个 `primary` 状态保存效价、唤醒度、当前关注点、关注显著度、未解决话题 ID 和当前活动，并可跨重启恢复。
- 显式衰减和启动衰减使用可配置半衰期。效价与唤醒度趋向中性；关注显著度低于界限后清除关注点。
- 每个聊天事件在 `TurnDecision` 后创建 `reaction` 或 `suppressed_reply` 记录。这些是确定性安全摘要，绝不是模型原始思维链。
- 想法、话题和活动必须引用已存在的 TrustedEvent。所有者控制 API 支持查看/更新状态、查看/创建/解决想法、创建/解决话题和查看活动；所有变更均写入审计。

## 活动证据

- 插件调用前，计算任务会启动 `calculator_task` 活动。
- 结束时记录成功/失败和证据 ID，随后清空当前活动，但保留活动历史。
- 执行认知仍只返回结构化任务结果；只有社交认知可以生成用户可见语言。

## 连续性审查器

- 模型响应把结构化 `ClaimEvidence` ID 与文本分开携带。
- 记忆声明要求当前范围内存在可访问的已提交记忆。
- 旧想法声明要求存在更早的 ThoughtRecord，且其所有来源事件属于当前会话。
- 行动声明要求同会话已完成活动，或同会话经过验证的工具审计记录。
- 因为尚无观点版本历史，观点变化声明会被阻止。缺乏证据的声明会触发社交认知回退和 `continuity.blocked` 审计。
- 模型响应文本和原始推理不会保存到 ThoughtRecord 或审计详情。

本阶段验证证据来源、可访问性、时间、状态和会话范围，但不能独立证明任意自由文本陈述与引用记录之间的语义蕴含。加入对应的认知事实审查前，模型提供方必须保持保守。

## 阶段验收

- `uv run pytest -q`：76 项通过。
- `uv run ruff check src tests migrations plugins`：通过。
- `uv run mypy`：80 个源文件通过。

测试覆盖自动 reaction/suppressed 记录、缺少来源拒绝、话题生命周期、计算活动证据、所有者授权、精确半衰期衰减、重启持久化、虚假/跨会话旧想法声明、有效同会话证据、连续性审计，以及持久层不包含原始模型推理。

## 阶段 4 之后延后

- ThoughtRecord 召回/排序和由模型生成的安全评估摘要。
- 带版本的观点和有证据的观点变化声明。
- 声明文本与证据之间的独立语义蕴含验证。
- UtteranceSession、SpeechUnit、中断、取消和重规划。
- 通用活动、日常规划、日记、睡眠巩固和梦境隔离仍属于阶段 8。
