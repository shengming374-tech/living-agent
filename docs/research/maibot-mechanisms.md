# 值得研究的 MaiBot 机制

研究版本：`73ef023c9c739af5e65a44361489b48ab7a5ed23`（官方 `Mai-with-u/MaiBot`，查阅于 2026-07-20）。

## 先判断参与，再生成内容

`src/maisaka/turn_gates.py` 和 `src/maisaka/reply_necessity.py` 会根据点名、直接请求、机器人近期出现情况、有效回复频率、消息压力和空闲时间决定是否进入规划。一个重要不变量是：只有沉默本身不能触发反复回复。LivingAgent 采用“发言是一种分级参与决策”这一机制思想，但将触发/等待替换为类型化 `observe/react/engage/act` 决策和明确的中断容忍度。

## 规划与表达分离

`src/maisaka/reasoning_engine.py`、`src/maisaka/chat_loop_service.py` 和 `src/chat/replyer/` 把规划/工具选择与最终表达分开。新消息到达时可以中断规划请求；回复工具会把回复引导和引用传给生成器。LivingAgent 采用分离和中断原则，同时施加更强合同：执行认知不能发送文本，只有社交认知持有表达权。

## 短回复塑形

`prompts/zh-CN/maisaka_replyer.prompt`、`src/chat/replyer/maisaka_generator_base.py` 和 `src/chat/utils/utils.py` 展示了实用的三段边界：回复器读取真实聊天历史并只生成口语化可见内容；输出规则排除分析和包装；独立后处理器限制消息长度和数量。

LivingAgent 独立实现后处理算法和类型化输出边界。社交 Prompt 按已记录的 GPL-3.0 来源直接复用部分自然语言风格句子。`TurnDecision` 为 `react` 选择一个短单元，为 `engage` 选择两到三个同样简短的语义单元；类型化 `UtteranceSession` 再通过绑定同一事件的平台授权投递。

## 对话存在感信号

发言判断衡量机器人近期在会话中的占比，而不是回复每一条消息。`src/maisaka/attention_drift.py` 把话题漂移限制在近期消息中的线索，并明确避免伪造低效率。LivingAgent 使用会话动量、当前关注点、未解决话题和真实活动记录；不会复制漂移 Prompt，也不会用随机错误模拟人类。

## 分层记忆召回

`src/maisaka/memory/mid_term.py` 把旧聊天压缩成可召回摘要；`src/maisaka/memory/heuristic_injector.py` 生成印象，并结合 Session/人物过滤和缓存限制搜索相关记忆。LivingAgent 采用保留来源、带范围的召回，并区分情景摘要与人物事实；额外加入强制候选防火墙、事实性标签、来源链、版本历史和严格跨会话访问检查。

## 插件宿主/运行器分离

`src/plugin_runtime/host/supervisor.py`、`host/rpc_server.py`、`runner/runner_main.py` 和 `protocol/envelope.py` 展示了宿主/运行器进程边界、类型化 RPC 信封、超时、健康检查、终止/强杀升级和能力服务。LivingAgent 独立实现更小的每插件 JSON-RPC 标准输入输出切片，并使用临时授权；不复用 MaiBot SDK 合同或代码。

## 保留的结论

- 在生成发言前决定是否参与以及参与强度。
- 让规划可中断，并丢弃过期回复计划。
- 每条社交消息保持简短；需要完整表达时使用少量语义单元，不发送一个长块，也不按标点机械分片。
- 跟踪近期存在感和会话节奏，而不是固定回复数量。
- 让召回记忆与当前用户消息在上下文中明确分离。
- 隔离插件失败，并由宿主强制执行超时。
