# LivingAgent 应用 / Applications

同一服务和控制台用于 macOS、iOS/iPadOS 和 Windows CLI。macOS 应用内置 Python 与全部运行时依赖；iOS 是连接你自己服务的客户端；Windows 有可携带 Python 的 CLI 压缩包，也能通过 pip/uv 安装。无需 Docker。

One runtime and Studio serve macOS, iOS/iPadOS and Windows CLI. macOS bundles Python and dependencies; iOS connects to your own runtime. Windows supports a portable Python bundle or pip/uv installation. Docker is not required.

## macOS

最低 macOS 14，分别在 Apple Silicon 或 Intel 主机上构建对应架构。安装 Xcode 与 uv 后，在仓库中运行：

macOS 14 or newer; build each architecture on its corresponding host. With Xcode and uv installed:

```bash
uv run python scripts/build_app.py
open dist/macos/LivingAgent.app
```

构建脚本按 `uv.lock` 安装依赖，内置可迁移的 CPython。输出 `.app`、DMG 和 SHA256SUMS。首次打开自动创建独立数据库、工作区、人格、提示词与随机管理令牌；令牌不进入 URL，网页只使用临时会话。退出应用时停止本机服务；应用异常退出后子服务也会检测父进程并停止。远程服务不会随客户端退出而停止。

The build uses `uv.lock` and relocatable CPython. It produces an app, DMG and checksums. First launch initializes a separate database, workspace, persona, prompts and random owner credential. Local servers stop with the app, including parent-process death; remote servers are independent.

数据目录 / Data directory:

```text
~/Library/Application Support/LivingAgent/
├── credentials.json           # 管理凭据 / owner credentials
├── living-agent.sqlite3       # 数据库 / database
├── workspace/                 # 默认文件工具范围 / default file scope
├── config/default.yaml        # 配置 / configuration
├── personas/default/          # 人格 / persona
├── prompts/                   # 提示词 / prompts
└── server.log                 # 本地服务日志 / local server log
```

CLI 与 macOS 应用使用同一个默认数据目录，但同一目录只允许一个运行时。CLI 连接应用运行时的方式：

The CLI shares the default profile and can connect to the app's runtime; a profile admits one runtime at a time:

```bash
living-agent status
living-agent chat '你好'
living-agent agent run '检查工作区并读取 README'
```

需要测试隔离时，可对原生应用设置 `LIVING_AGENT_APP_DATA_DIR`，或对 CLI 使用 `--data-dir`。构建目录和运行目录彼此独立，不会复制仓库中的 `.env`、数据库、登录态或审计材料到应用。

For isolated tests, use `LIVING_AGENT_APP_DATA_DIR` on the native app or `--data-dir` on the CLI. Bundles do not copy source-checkout secrets, databases or login state.

默认构建使用 ad hoc 签名，适合本机验证。对外分发需要你自己的 Developer ID 签名与公证；可使用 `--identity 'Developer ID Application: ...'` 构建，随后完成公证。当前没有自动申请证书或向 App Store 上传。

Default builds use ad hoc signing for local validation. Public distribution requires your Developer ID and notarization. `--identity` selects a signing identity; notarization and store publication are separate steps.

## iOS / iPadOS

最低 iOS 17。打开 `apps/apple/LivingAgent.xcodeproj`，选择 LivingAgent scheme 和 iPhone/iPad。首次打开填写 HTTPS 服务地址、所有者 ID 和管理令牌。原生客户端使用系统钥匙串保存连接配置，使用临时 WKWebView 数据存储；凭据注入和页面导航限制在配置的确切 origin，不跟随凭据请求的重定向。

iOS 17 or newer. Open the Xcode project and choose an iPhone/iPad. Enter your HTTPS runtime origin, owner ID and token. Credentials use Keychain and an ephemeral WKWebView, scoped to the exact origin. Authenticated connection probes reject redirects.

```bash
xcodebuild -project apps/apple/LivingAgent.xcodeproj \
  -scheme LivingAgent -configuration Release -sdk iphonesimulator \
  -derivedDataPath build/ios CODE_SIGNING_ALLOWED=NO build
```

iOS 不内置 Python，不在 iPhone 上执行桌面 Shell 或插件，不承诺后台持续运行。它能使用服务提供的对话、群聊、目标控制、记忆与人格管理。持续工作由 macOS/服务器承担。真机安装、TestFlight 和 App Store 需要在 Xcode 里选择你的开发团队和签名配置。

iOS does not embed Python, execute desktop tools on the phone, or promise continuous background execution. It controls chats, rooms, goals, memory and persona on the service. Device installation and store distribution need your signing team.

连接手机前，为服务配置 HTTPS 反向代理。代理可连接本机默认回环监听端口，无须把无加密管理端口暴露到局域网或公网。手机输入代理的 HTTPS origin；令牌可在本机通过以下明确命令读取（不要写入截图或公开文档）：

Use an HTTPS reverse proxy to the loopback service before connecting a phone. Retrieve the owner credential locally:

```bash
living-agent credentials --reveal
```

## Windows CLI

Windows 10/11，Python 3.12+。安装源代码开发版：

Windows 10/11 with Python 3.12+. Development installation:

```powershell
uv sync --frozen
uv run living-agent init
uv run living-agent serve
```

或安装 wheel / Or install a wheel:

```powershell
py -3.12 -m pip install .\living_agent-0.3.0-py3-none-any.whl
living-agent init
living-agent serve
```

便携版在 Windows 主机或 GitHub Actions Windows runner 上构建：

Build the portable bundle on Windows or the Windows CI runner:

```powershell
uv run python scripts/build_app.py
```

解压 `LivingAgent-windows-x64.zip`，在 `LivingAgent-CLI` 目录运行 `living-agent.cmd serve`。无需系统 Python，也无需管理员权限。另一个终端可运行：

Extract the zip and run `living-agent.cmd serve`. No system Python or administrator permission is needed. In another terminal:

```powershell
.\living-agent.cmd status
.\living-agent.cmd chat "你好"
.\living-agent.cmd tools
.\living-agent.cmd agent run "检查工作区并读取 README"
.\living-agent.cmd agent list
.\living-agent.cmd agent show RUN_ID
.\living-agent.cmd agent resume RUN_ID --message "README 在 docs 目录"
.\living-agent.cmd agent confirm RUN_ID
.\living-agent.cmd agent cancel RUN_ID
```

默认数据在 `%LOCALAPPDATA%\LivingAgent`，服务只监听 `127.0.0.1:8765`。没有可用 OS 插件沙箱的平台不允许生产模式监听外部地址；Windows 不提供与 macOS sandbox-exec 等价的插件隔离。Windows CLI 适配不等于所有 OS 专用插件功能都可用。

Data lives under `%LOCALAPPDATA%\LivingAgent`; default listening is `127.0.0.1:8765`. Windows has no equivalent plugin sandbox in this project. Production external binding fails closed when an enforced backend is unavailable. Platform adaptation does not imply OS-specific sandbox features exist everywhere.

跨端连接 CLI 必须明确设置远程专用凭据，本地凭据不会按任意 `--url` 自动转发：

Explicit remote credentials are required; local secrets are never forwarded to arbitrary `--url` values:

```powershell
$env:LIVING_AGENT_CLIENT_ACTOR = "owner-local"
$env:LIVING_AGENT_CLIENT_TOKEN = "你的服务管理令牌"
.\living-agent.cmd --url https://agent.example.com status
```

## 多智能体群聊 / Multi-agent rooms

应用导航中的“多智能体群聊”允许创建 2–6 位成员，每位有独立名字和人格。成员共用服务配置的模型，按顺序读取最近群聊上下文并发言；每条用户消息最多触发每位选中成员一次。可点名、停止正在生成的回复、重启后继续查看记录。没有无限循环，也不会因为群成员说“运行命令”就执行工具。

Rooms contain 2–6 members with distinct names and personas, sharing the configured model. Each selected member replies once per owner message, in order, reading prior replies. Mentions, cancellation and durable history are supported. Group speech grants no tool authority.

CLI 创建成员文件并发消息 / Create a members file and send messages from the CLI:

```json
[
  {"name": "小麦", "persona": "温暖、重视关系与情绪"},
  {"name": "探索者", "persona": "好奇、善于构思，提出具体例子"},
  {"name": "审阅者", "persona": "冷静、重视证据，指出风险并给出改进办法"}
]
```

```bash
living-agent group create '圆桌' --members members.json
living-agent group list
living-agent group send ROOM_ID '讨论一下如何改进我的计划'
living-agent group show ROOM_ID
living-agent group stop ROOM_ID
```

每个实例最多 100 个群聊，每个群最多 500 条消息，最近 16 条作为当前发言上下文。群聊是服务端独立的讨论工作流，不把讨论内容直接写入主人格事实记忆。暂不支持成员独立模型提供方、无限长历史、群内自动执行工具或多个实例共同驱动同一个群。中断轮次在重启时标记 interrupted，不自动重复调用付费模型。模型失败保留已收到的消息和已完成的成员发言。

Limits: 100 rooms, 500 messages per room, latest 16 messages per reply. Discussion does not directly write core factual memory. Per-member providers, unbounded history, group tool execution and multi-instance orchestration are not implemented. Restart marks interrupted rounds without replaying paid calls. Failure retains received messages and completed replies.

默认 mock 的成员发言带“演示”标记。配置 `openai_compatible` 才会产生真实模型讨论。在运行目录的 `.env` 中配置模型并重启服务；可复制仓库 `.env.example` 中的模型变量，不能把它打包进应用。

The default mock labels replies as demonstrations. Configure `openai_compatible` in the profile's `.env` and restart for actual model discussion; do not bundle API keys.
