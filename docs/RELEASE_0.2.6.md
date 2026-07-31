# LivingAgent 0.2.6

0.2.6 是一次全功能可靠性修复，不扩大 README 已声明的功能范围。

## 修复

- Wheel 和 sdist 通过白名单构建，包含迁移、默认配置、人格、提示词、控制台和计算器插件，不包含虚拟环境、数据库、备份、缓存或本地秘密。
- Wheel 首次启动把可编辑默认资产复制到 `LIVING_AGENT_RUNTIME_ROOT`；已有文件不覆盖，部分目录或无效自定义路径明确失败。
- Alembic 直接使用只读包资源，不依赖当前目录或仓库的 `alembic.ini`。
- NapCat 使用 256 条有界入站 FIFO 和可配置工作并发，动作回包始终优先关联；失败动作保持最多发送一次。
- 模型对连接、超时和指定瞬时 HTTP 错误执行可取消的有界重试，审计记录安全错误类别和尝试次数。
- 模型最终失败时社交入口保持静默，不创建或投递发言；技术错误仅保留在脱敏审计中。
- 控制台使用单次管理会话探测后再加载 12 个真实视图，并消除密码表单警告和 favicon 404。

## 新配置

- `LIVING_AGENT_RUNTIME_ROOT=.`
- `LIVING_AGENT_NAPCAT_MAX_QUEUED_EVENTS=256`
- `LIVING_AGENT_MODEL_MAX_ATTEMPTS=2`
- `LIVING_AGENT_MODEL_RETRY_BASE_SECONDS=0.5`
- `LIVING_AGENT_MODEL_RETRY_MAX_SECONDS=5`

## 兼容性

现有 API、数据库表和平台消息格式保持兼容。新增受现有管理 Bearer 边界保护的 `GET /v1/management/session`。本版本不新增语音、视频、通用附件、图片生成、主动发送或开放式动作规划。
