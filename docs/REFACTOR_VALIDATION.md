# 0.3.0 验收 / Version 0.3.0 validation

日期 / Date: 2026-10-01

## 验证结果 / Results

- Python 全套：496 passed。
- OpenClaw bridge：14 passed。
- Ruff、Mypy（159 个源文件）、JavaScript 语法、`uv lock --check`、`git diff --check`：通过。
- 浏览器实际提交目标，执行中自动刷新进度，真实列目录与读取 README，完成展示和取消成功；目标输入未被刷新覆盖，检查到的页面错误日志为空。
- 主运行时从 0.2.6 的 1293 行拆到 904 行，独立模块承接模型调用、结果呈现、交付记录与记忆探针。

The full Python suite, Node bridge tests, lint/type checks and lock/syntax checks passed. Browser acceptance exercised actual goal execution and cancellation against an isolated local server. The runtime separates concrete responsibilities while preserving the existing regression suite.

## 功能回归 / Functional regressions

新 Agent 测试包括真实临时工作区读写、精确确认、失败反馈和补充输入、结构化模型协议、恢复不重放、版本冲突、并发继续/取消、生命周期审计中断、运行中进程清理、短写影响保留证据，以及写后重新读取。

结果呈现回归证明 Agent 使用社交人格、执行总结是单独标记的模型输出、工具结果保留来源、无记录的记忆声明被阻止、过期平台结果不投递；模拟器不调用模型或产生影响。

功能补齐回归覆盖插件 API 启停后实际关机重启、损坏状态全部禁用并可显式修复，日计划替换/重置/重复完成与跨日期活动隔离，以及项目无效空值更新。

安全回归覆盖生产伪所有者调用在 runtime 前被拒绝、合法 Bearer 工作流程、分块和伪报长度请求上限、Shell 选项内嵌/符号链接路径，以及 DNS 地址绑定、重定向独立验证、实际 peer 核验和原域名 TLS/SNI。DNS 测试使用记录型内存网络后端，不连接真实公网。

Regression tests validate effectful behavior and persistence, not just empty-method scans. Networking protocol tests use offline transports; production identity rejection is checked before events, users or tasks can be created.

## 安装包验收 / Installed-package acceptance

Wheel 与 sdist 成功构建。Wheel 安装到新的 Homebrew Python 3.12.13 环境，在空运行目录从 site-packages 启动：

- `/health` 返回版本 `0.3.0`；控制台、管理会话和 11 个工具声明均可读取。
- Agent 演示 `completed`：3 次决策、2 个真实工具观察，保存读取内容及证据。
- 沙箱计算器实际得到 `7 * 8 = 56`。
- 插件关闭后创建新的应用实例，仍保持关闭，重新启用成功。
- 数据库迁移头为 `0014_agent_runs`。
- 包含 Agent、API、控制台、迁移及运行资产；不包含本地 .env、数据库或虚拟环境。

Source checks use locked dependencies. Installed-wheel acceptance also exercises fresh dependency resolution within declared version ranges, independently of the source checkout.

## Python 与沙箱 / Python and sandbox

源码全套使用独立 Homebrew Python 和本地字节码缓存，保留用户原 .venv 与数据库。旧虚拟环境曾发生云盘文件读取阻塞，没有重建或删除它。

真实 uv Python `3.12.13`（位于主目录）也被测试直接选中，在 sandbox-exec 下执行计算器 `6 * 7 = 42`。临时目录及 Home 临时目录的探针证实读取、写入、联网和派生进程均被阻止；仅标准库和必要运行文件获得只读例外，site-packages/.pth 不加载。未声称在 uv 解释器中运行了整个 Python 套件。

Real home-installed uv Python passed sandbox worker execution and isolation probes. Only standard-library/runtime reads were added; the home-directory denial and write/network/process restrictions remain. The full source suite was run with Homebrew Python.

## 复现 / Reproduce

```bash
uv sync --all-groups --frozen
uv run pytest -q
uv run ruff check .
uv run mypy
node --check src/living_agent/studio/app.js
npm test --prefix integrations/openclaw/living-agent-bridge
uv lock --check
git diff --check
uv build
```

## 验证边界 / Limits

未调用真实云端模型，也未发送真实 QQ/微信消息；不能由本地通过推断开放式规划质量或平台送达。完成证据核验成功工具结果，不证明任意自然语言目标的语义满足。生产数据库未在本次测试中迁移。取消不回滚已有影响，多 worker 分布式执行未实现。

No live cloud model or QQ/WeChat delivery was exercised. Evidence-linked completion does not prove arbitrary semantic goal satisfaction. Production data was not migrated during these isolated checks.
