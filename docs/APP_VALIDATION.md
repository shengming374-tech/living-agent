# 应用验收 / Application validation

2026-10-01，基于 0.3.0 的跨平台应用与群聊实现。运行数据、密钥、数据库和审计材料未打入安装包。

Cross-platform apps and rooms built on 0.3.0. Bundles exclude checkout credentials, databases and audit material.

| 平台 / Platform | 验收 / Evidence |
| --- | --- |
| macOS arm64 | 原生 SwiftUI/WKWebView 应用与内置 CPython；全新中文、空格目录启动，健康检查、11 个工具、两位群成员回复、重启历史、真实沙箱计算器；启动前后严格签名检查。 / Native app and bundled runtime; fresh Unicode profile, health, tools, replies, durable history, sandboxed calculator, signature verification before and after use. |
| iOS/iPadOS | Xcode iOS Simulator 构建、模拟器安装启动；HTTPS 服务连接客户端。 / Simulator build and launch; HTTPS runtime client. |
| Windows x64 | GitHub Actions Windows runner 构建与便携运行时验收，见下方工作流。 / Portable build and runtime acceptance on the Windows CI runner linked below. |

源码回归：515 项 Python 测试通过；34 项配置、CLI、群聊和插件专项测试通过；14 项 Node bridge 测试通过。前一轮完整回归出现过一条 SQLAlchemy 连接回收警告，最新一轮未出现。Ruff、Mypy（167 个源文件）和锁文件检查通过。移动网页已验证对话、点名、群聊和 390px 宽度，无横向溢出或控制台错误。

Source validation: 515 Python tests, 34 focused tests and 14 Node bridge tests pass. A prior full run emitted a SQLAlchemy connection cleanup warning; the latest did not. Ruff, Mypy and lock checks pass. Mobile Studio chat, mentions, rooms and 390px layout are verified without overflow or console errors.

尚无 iPhone/iPad 真机、TestFlight/App Store、Developer ID 公证、真实云模型讨论或 QQ/微信发送证据。iOS 端不在设备上运行 Python；默认 mock 回复明确标记为演示。Windows 没有本项目的 OS 插件沙箱，平台专用能力边界详见 [APPS.md](APPS.md)。

No physical-device, store distribution, notarization, live cloud-model discussion or live messaging delivery evidence is claimed. iOS uses a remote runtime. Mock replies are labeled demonstrations. Windows sandbox limitations are documented in [APPS.md](APPS.md).

代码与构建 / Code and builds: [PR #7](https://github.com/shengming374-tech/living-agent/pull/7), [跨平台工作流 / Application workflow](https://github.com/shengming374-tech/living-agent/actions/workflows/apps.yml).
