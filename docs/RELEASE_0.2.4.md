# 0.2.4：可信用户工作、确认式 Shell 与记忆生命周期

0.2.4 在现有能力代理和持久任务内核上增加一个默认开启的确认式 Shell 垂直切片，同时补齐自然语言任务控制、受信任管理员工作边界，以及自动/手动记忆的冲突生命周期。

## 可信用户通过语言工作

- `owner_id` 和部署方明确配置到 `admin_ids` 的身份可以提出工作区、每日计划和 Shell 任务。
- 身份仍只来自认证适配器的稳定 ID；昵称、群角色、消息自称和记忆不能授予管理员权限。
- 管理员可以执行允许的只读工作，但写入和进程启动仍必须由配置的所有者确认。
- 聊天新增“查看任务”“取消任务”，与已有“确认任务”一起覆盖任务提出、等待、执行、查询、恢复和终止。

## 确认式 Shell

- `shell.command.execute` 默认开启，可通过 `LIVING_AGENT_WORK_SHELL_ENABLED=false` 显式关闭。
- 自然语言目录支持“运行测试”“运行代码检查”“运行类型检查”“查看 git 状态”，以及显式的“运行命令 \`...\`”。
- 执行器使用 `create_subprocess_exec` 运行精确 argv，不调用 `sh -c`，不支持管道、重定向或环境变量展开。
- cwd 必须在工作区内；命令名必须进入部署白名单；绝对路径、父目录逃逸、敏感路径、危险 Git 子命令和不受限 `uv run` 会被拒绝。
- 每次进程启动都进入 `waiting_confirmation`。被中断的进程步骤在重启后重新请求确认，不会自动重放。
- 子进程使用最小环境、统一 stdout/stderr 总量上限和超时；超时或取消会先 TERM 整个进程组，再 KILL。
- 退出码、cwd、argv 摘要、输出大小与摘要进入宿主证据和审计。进程输出继续视为不可信工具数据。

Shell 切片不是完整操作系统沙箱。测试、类型检查器插件和仓库内工具仍可能执行工作区代码；生产部署前应使用专用低权限账户或容器、缩小命令白名单，或显式关闭 Shell。

## 自动与手动记忆

- 自动提取发现等价活跃记忆时去重，不再创建重复节点。
- 同主题的新事实与活跃记忆冲突时，候选保持 `pending` 并标记 `conflicting_memory_requires_review`，不会被自动覆盖或提前拒绝。
- 所有者可用 `replace_conflicts=true` 提交冲突候选；新节点生效时旧节点软删除，并追加 `superseded` 版本记录。
- `POST /v1/memories/manual` 提供保留候选防火墙、来源和事实性校验的一步式手动记忆入口。
- 所有替换都会同步更新现实记忆向量，并留下被替换节点与新节点的审计关联。

## 生命周期与 MaiBot 参考

- 启动恢复继续把中断的写入和进程步骤送回确认；关闭流程会停止夜间调度、关闭模型/工作/嵌入资源，并写入 `runtime.stopping` 与 `runtime.stopped`。
- 只读研究了固定 MaiBot 修订中的统一工具规格、后台任务启动/取消以及重证据人物事实写回机制。
- LivingAgent 没有复制 MaiBot 的工具模型、生命周期函数或记忆运行时代码；实现仍基于自身类型化合同、权限代理、来源链和测试。

## 主要配置

```yaml
admin_ids: []
work_shell_enabled: true
work_shell_allowed_executables:
  - git
  - mypy
  - pwd
  - pytest
  - rg
  - ruff
  - uv
work_shell_timeout_seconds: 30.0
work_shell_max_output_bytes: 262144
```
