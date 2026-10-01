# 研究来源记录 / Research Provenance

## 参考仓库身份

- 仓库：`https://github.com/Mai-with-u/MaiBot.git`
- 修订版本：`73ef023c9c739af5e65a44361489b48ab7a5ed23`
- 查阅时分支：`main`
- 查阅日期：2026-07-20
- 参考仓库许可证：GNU GPL 第 3 版
- 本地副本：`references/maibot/`（被 Git 忽略的只读研究材料）

## 查阅文件与研究目的

| 参考文件 | 研究目的 |
| --- | --- |
| `README.md`、`LICENSE` | 项目目标与许可证边界 |
| `src/maisaka/turn_gates.py` | 回复必要性、频率、空闲补偿和沉默不变量 |
| `src/maisaka/reply_necessity.py` | 参与信号与近期存在惩罚 |
| `src/maisaka/attention_drift.py` | 基于上下文线索的联想，而非随机走神 |
| `src/maisaka/reasoning_engine.py` | 可中断规划与工具阶段分离 |
| `src/maisaka/chat_loop_service.py` | 规划器上下文/工具循环与 Hook 位置 |
| `src/chat/replyer/replyer_manager.py` | 每 Session 回复生成器的所有权 |
| `src/chat/replyer/maisaka_generator.py` | 独立回复生成层 |
| `src/chat/replyer/maisaka_generator_base.py` | 仅回复输出边界与真实历史过滤 |
| `prompts/zh-CN/maisaka_replyer.prompt` | 口语化可见回复目标；部分 Prompt 已注明来源后复制 |
| `src/config/official_configs.py` | 只查阅 `reply_style`、群聊和私聊 Prompt 字符串值；未复制 Python 实现 |
| `src/chat/replyer/maisaka_generator_base.py` | 只复制最终可见输出 Prompt 字符串；未复制生成器代码 |
| `src/chat/utils/utils.py` | 有界生成后消息数量概念；未复制算法 |
| `src/maisaka/builtin_tool/reply.py` | 规划到表达的交接和分段发送概念 |
| `src/maisaka/memory/mid_term.py` | 紧凑摘要和召回线索 |
| `src/maisaka/memory/heuristic_injector.py` | 带范围、有限频率的记忆召回 |
| `src/services/memory_flow_service.py` | 人物事实回写的证据选择 |
| `src/core/tooling.py` | 工具声明、调用上下文和结构化执行结果的分离 |
| `src/A_memorix/core/runtime/lifecycle_orchestrator.py` | 后台任务幂等启动、统一取消和关闭等待 |
| `src/chat/image_system/image_manager.py` | 图片描述、识别结果复用和失败降级的机制研究 |
| `src/chat/message_receive/message.py`、`image_receive_compressor.py` | 入站图片数量与大小边界的机制研究 |
| `src/maisaka/visual/mode_utils.py`、`message_limiter.py` | 直接多模态与文本观察模式选择、上下文图片上限 |
| `src/maisaka/visual/chat_history_refresher.py` | 迟到识别结果刷新占位的机制研究 |
| `src/maisaka/reasoning_engine.py` | 文本规划前的有界识图等待与降级 |
| `src/config/official_configs.py`、`src/config/model_configs.py` | 视觉任务分离和模式配置概念；未复制字段或实现 |
| `src/core/tooling.py` | 类型化工具规格、调用与结果 |
| `src/plugin_runtime/protocol/envelope.py` | 类型化 RPC 信封概念 |
| `src/plugin_runtime/host/rpc_server.py` | 宿主强制 RPC 超时 |
| `src/plugin_runtime/host/supervisor.py` | 运行器生命周期与终止/强杀升级 |
| `src/plugin_runtime/runner/runner_main.py` | 独立插件运行器职责 |

## 借用声明

LivingAgent 没有复制 MaiBot 的 Python/JavaScript 源代码、模式、运行时名称或目录结构，也没有逐行翻译任何代码。LivingAgent 运行时仍是在自身类型化合同和测试之上从零实现的独立项目。

0.2.0 图片处理只借鉴视觉识别与回复分层、显式模式选择、结果复用和成本上限这些抽象机制。`auto/caption/direct` 路由、结构化视觉观察模式、内容摘要缓存、来源/污染传播、错误码和测试均为 LivingAgent 独立设计；没有复制 MaiBot 视觉 Prompt、数据库模式、后台任务、占位刷新器或控制流程。

所有者于 2026-07-21 明确授权直接复用 Prompt。以下中文自然语言 Prompt 摘录已复制到 `prompts/social/reply.txt`：

- 阅读之前聊天、把握当前话题并以日常口语回复的要求；
- 默认平淡、简短、不过度修饰的回复风格段落；
- 简短、单话题的群聊注意规则和参与频率措辞；
- 简短的私聊注意规则；
- 只输出可见发言、不添加包装或点名的要求。

这些摘录来自固定版本的 `prompts/zh-CN/maisaka_replyer.prompt`，以及嵌入 `src/config/official_configs.py` 和 `src/chat/replyer/maisaka_generator_base.py` 的 Prompt 字符串值。只复制了自然语言字符串，没有复制周围的 Python 控制流程。

MaiBot 使用 GPL-3.0。复制的 Prompt 摘录仍受该许可证约束，并在 `THIRD_PARTY_NOTICES.md` 中标明；`LICENSES/MaiBot-GPL-3.0.txt` 随项目提供 GPL-3.0 全文。本来源记录不会因为 Prompt 不是可执行代码，就声称其不受著作权保护。

## 2026-09-30 架构重构 / Architecture refactor

再次查阅 [MaiBot 官方首页](https://github.com/Mai-with-u/MaiBot)，参考其自然交流、参与时机、持续了解用户的公开设计目标。新增目标循环、共享工具目录、持久检查点及状态 API 为 LivingAgent 独立实现；此次未复制新的上游代码或提示词。旧机制研究仍绑定上文所列的固定修订，不声称代表当前所有上游实现。

The official overview was revisited for social design goals. The new agent loop and checkpoints are original implementations. Earlier source studies remain pinned to their recorded revision.
