# LivingAgent 0.3.0 / Release notes

日期 / Date: 2026-10-01

0.3.0 将人格社交与自主目标执行接成可持久化的 Agent：观察真实工具结果，选择下一步，保存检查点，再执行。原有确定性任务命令、分层记忆、人格版本和平台适配器继续沿用。

Version 0.3.0 connects social persona and autonomous goals through a persistent observe/decide/act loop. Existing deterministic commands, scoped memory, persona versions and platform adapters remain available.

## Agent 功能 / Agent features

- 统一目录声明 11 个已有受控工具，模型提出下一步，宿主生成身份、权限请求、来源链与子任务。
- 真实执行结果反馈、失败修正、补充信息、精确动作确认、取消、重启暂停与恢复；完成声明必须引用成功工具证据。
- 有界决策次数、每次决策超时与连续重复动作检测；恢复和补充不会重置决策预算。
- 聊天入口 `agent:`、`智能体:`、`自主任务:`，管理 API `/v1/agent/runs`，控制台 `/studio#agent` 自动显示执行进度、参数、补充和结果。
- Mock 可真实列出工作区并读取 README；目录缺少 README 时可补充有效文件路径。开放式任务需配置 `openai_compatible`。

The model selects one next action from 11 shared tool declarations. Host-owned contracts retain authority and provenance. Goals support clarification, exact confirmation, cancellation and checkpoint recovery. Completion references successful observed evidence. Mock performs real filesystem operations; open-ended planning requires a configured model.

## 运行时与功能补齐 / Runtime and functional repairs

主运行时按职责拆分：`OutcomePresenter` 统一任务与 Agent 的人格结果呈现，`ModelCalls` 统一社交模型调用审计与连续性检查，`DeliveryRecorder` 记录实际采用的消息，`MemoryProbeRunner` 处理隔离探针。对话任务路由独立于主聊天流程。

The runtime separates scheduling, outcome presentation, model auditing, delivery recording and memory probes. Agent results now enter the shared social persona, carry separated tool evidence, and undergo continuity checks. Superseded platform replies are discarded before delivery.

- 修复 Agent 结果直接暴露执行总结、补充路径不生效，以及重复读取被全历史重复检测误拦的问题。
- 取消中断活动驱动并收束子任务；恢复前重读子任务当前状态，已完成影响不重放，需确认的影响保留再确认规则。
- 插件启停保存到运行目录 `data/plugin-state.json`，重启恢复所有者选择；配置 `enabled_plugins` 是首次默认值。
- 日计划批量保存、替换、重置与完成同步活动历史；同名条目按日期计划隔离，重复完成不重复记账。
- 项目更新显式传入无效 `null` 返回 422，保留原数据。
- 模拟器可预览 Agent 路由，不调用模型、创建任务或产生影响。
- 生产直接聊天的认证声明必须通过 Bearer 校验；所有 API 请求按实际接收字节限制大小，包含分块请求。
- Shell 检查 `--option=path` 内嵌路径及符号链接范围；网页连接绑定已验证公网地址并保留域名 TLS 校验。

Functional repairs cover clarification paths, cancellation and child recovery, consecutive repetition checks, persistent plugin switches, plan/activity synchronization, invalid project updates and side-effect-free agent previews.

## 升级与运行 / Upgrade and run

```bash
uv sync --all-groups --frozen
uv run uvicorn --app-dir src living_agent.app:app --host 127.0.0.1 --port 8000
```

启动自动应用新增迁移 `0014_agent_runs`，保留原有任务、记忆和人格。中断目标暂停，所有者选择继续；单次写入和进程操作仍逐次确认。使用一个 Uvicorn worker，共享数据库的多 worker 执行未实现。

Startup applies additive migration `0014_agent_runs`. Interrupted goals pause for explicit resumption. Existing write/process confirmation rules remain. Run one application worker; distributed execution leases are not implemented.

**直接聊天兼容变更 / Direct-chat compatibility:** 生产或已配置管理令牌时，`/v1/chat` 的 `authenticated=true` 请求必须携带现有 `Authorization: Bearer <management_api_token>`。匿名 `authenticated=false` 社交和平台适配器各自的认证方式继续可用。

## 验证与边界 / Validation and limits

可复现的检查、安装包验收和环境说明见 [验收记录](REFACTOR_VALIDATION.md)，操作与状态规则见 [Agent runtime](AGENT_RUNTIME.md)。

本地验证使用临时目录、独立数据库、Mock/脚本模型和 HTTP MockTransport。未验证真实云模型的规划质量或 QQ/微信送达。工具证据证明操作确实成功，不等同于任意自然语言目标的语义证明。取消保留已完成影响。语音、视频、通用附件和业务连接器仍未实现。

Local tests exercise isolated files/databases, scripted models and HTTP mock transport. Live cloud planning quality and QQ/WeChat delivery remain unverified. Observed tool success does not prove arbitrary semantic goal satisfaction, and cancellation does not undo completed effects.
