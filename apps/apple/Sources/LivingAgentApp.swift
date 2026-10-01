import SwiftUI
import WebKit
import Security
#if os(macOS)
import AppKit
#endif

// 凭据只存 Keychain; 网页使用临时会话 / Secrets stay in Keychain, web sessions are ephemeral.
enum CredentialStore {
    static let service = "tech.livingagent.connection"
    static func read() -> Data? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: "remote",
            kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        return SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess ? result as? Data : nil
    }
    static func save(_ data: Data) throws {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: "remote"]
        let attributes: [String: Any] = [kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            let insert = query.merging(attributes) { _, new in new }
            guard SecItemAdd(insert as CFDictionary, nil) == errSecSuccess else { throw AppError.keychain }
        } else if status != errSecSuccess { throw AppError.keychain }
    }
    static func clear() {
        SecItemDelete([kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: "remote"] as CFDictionary)
    }
}

enum AppError: LocalizedError {
    case invalidURL, missingCredentials, unauthorized, keychain, missingRuntime, startup, timeout
    var errorDescription: String? {
        switch self {
        case .invalidURL: return "请输入 HTTPS 服务地址，例如 https://agent.example.com（不要附加路径）"
        case .missingCredentials: return "请输入所有者 ID 和不少于 32 个字符的管理令牌。"
        case .unauthorized: return "连接失败，请检查服务地址、所有者 ID 和管理令牌。"
        case .keychain: return "无法保存连接凭据到系统钥匙串。"
        case .missingRuntime: return "应用缺少内置运行时，请使用 build_macos.py 构建完整应用。"
        case .startup: return "本地服务启动失败，可查看数据目录中的 server.log。"
        case .timeout: return "服务启动超时，请查看 server.log。"
        }
    }
}

struct Connection: Codable, Hashable {
    let url: String
    let actor_id: String
    let token: String
    var studio: URL { URL(string: url + "/studio#chat")! }
}

// No redirects can carry the owner's Bearer to another origin / 拒绝凭据请求重定向。
final class NoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

@MainActor final class AppModel: ObservableObject {
    @Published var connection: Connection?
    @Published var starting = false
    @Published var error: String?
    @Published var reloadID = UUID()
    @Published var showSettings = false
    @Published var serverURL = ""
    @Published var actorID = "owner-local"
    @Published var token = ""
    #if os(macOS)
    private var backend: Process?
    private var logHandle: FileHandle?
    private var readyFile: URL?
    private var terminationObserver: NSObjectProtocol?
    #endif
    private var operation: Task<Void, Never>?

    init() {
        if let data = CredentialStore.read(), let saved = try? JSONDecoder().decode(Connection.self, from: data) {
            serverURL = saved.url; actorID = saved.actor_id; token = saved.token
            connection = saved
        }
        #if os(macOS)
        terminationObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification, object: nil, queue: .main
        ) { [weak self] _ in MainActor.assumeIsolated { self?.stopLocal() } }
        if connection == nil { startLocal() }
        #else
        if connection == nil { showSettings = true }
        #endif
    }

    func connectRemote() {
        guard let components = URLComponents(string: serverURL.trimmingCharacters(in: .whitespacesAndNewlines)),
              components.scheme == "https", let host = components.host, !host.isEmpty,
              components.user == nil, components.password == nil, components.query == nil,
              components.fragment == nil, ["", "/"].contains(components.path) else {
            error = AppError.invalidURL.localizedDescription; return
        }
        let actor = actorID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !actor.isEmpty, token.count >= 32 else {
            error = AppError.missingCredentials.localizedDescription; return
        }
        var origin = components
        origin.path = ""
        if origin.port == 443 { origin.port = nil }
        guard let normalized = origin.url?.absoluteString else { return }
        let candidate = Connection(url: normalized, actor_id: actor, token: token)
        operation?.cancel()
        starting = true; error = nil
        operation = Task {
            let session = URLSession(configuration: .ephemeral, delegate: NoRedirect(), delegateQueue: nil)
            defer { session.invalidateAndCancel(); if !Task.isCancelled { starting = false } }
            do {
                var request = URLRequest(url: URL(string: candidate.url + "/v1/management/session")!)
                request.timeoutInterval = 20
                request.setValue("Bearer " + candidate.token, forHTTPHeaderField: "Authorization")
                request.setValue(candidate.actor_id, forHTTPHeaderField: "X-Actor-ID")
                let (_, response) = try await session.data(for: request)
                guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw AppError.unauthorized }
                try Task.checkCancellation()
                try CredentialStore.save(JSONEncoder().encode(candidate))
                #if os(macOS)
                stopLocal()
                #endif
                connection = candidate; showSettings = false
            } catch is CancellationError { }
            catch { if !Task.isCancelled { self.error = error.localizedDescription } }
        }
    }

    func disconnect() {
        operation?.cancel()
        #if os(macOS)
        stopLocal()
        #endif
        connection = nil; token = ""; starting = false
        CredentialStore.clear()
        showSettings = true
    }

    #if os(macOS)
    private var dataDirectory: URL {
        if let custom = ProcessInfo.processInfo.environment["LIVING_AGENT_APP_DATA_DIR"] {
            return URL(fileURLWithPath: custom, isDirectory: true)
        }
        return FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("LivingAgent", isDirectory: true)
    }
    func startLocal() {
        operation?.cancel(); stopLocal()
        CredentialStore.clear()
        connection = nil; starting = true; error = nil
        operation = Task {
            do {
                let root = dataDirectory
                try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true,
                                                        attributes: [.posixPermissions: 0o700])
                let python = Bundle.main.resourceURL!.appendingPathComponent("runtime/bin/python3")
                guard FileManager.default.isExecutableFile(atPath: python.path) else { throw AppError.missingRuntime }
                let ready = root.appendingPathComponent(".ready-\(UUID().uuidString).json")
                readyFile = ready
                let log = root.appendingPathComponent("server.log")
                if !FileManager.default.fileExists(atPath: log.path) {
                    FileManager.default.createFile(atPath: log.path, contents: nil,
                                                   attributes: [.posixPermissions: 0o600])
                }
                logHandle = try FileHandle(forWritingTo: log)
                try logHandle?.seekToEnd()
                let child = Process()
                child.executableURL = python
                child.arguments = ["-I", "-m", "living_agent", "--data-dir", root.path,
                                   "serve", "--port", "0", "--ready-file", ready.path,
                                   "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
                child.currentDirectoryURL = root
                var env = ProcessInfo.processInfo.environment
                // Do not inherit source-checkout configuration / 不继承源仓库配置。
                for key in env.keys where key.hasPrefix("LIVING_AGENT_") || key.hasPrefix("PYTHON") {
                    env.removeValue(forKey: key)
                }
                env["PYTHONUNBUFFERED"] = "1"
                child.environment = env
                child.standardOutput = logHandle; child.standardError = logHandle
                backend = child
                child.terminationHandler = { [weak self] _ in
                    Task { @MainActor in
                        guard self?.backend === child else { return }
                        self?.backend = nil
                        self?.connection = nil
                        self?.starting = false
                        self?.error = AppError.startup.localizedDescription
                    }
                }
                try child.run()
                for _ in 0..<1200 {
                    try Task.checkCancellation()
                    if !child.isRunning { throw AppError.startup }
                    if let data = try? Data(contentsOf: ready) {
                        let local = try JSONDecoder().decode(Connection.self, from: data)
                        guard local.url.hasPrefix("http://127.0.0.1:"), local.token.count >= 32 else { throw AppError.startup }
                        connection = local; starting = false; showSettings = false
                        try? FileManager.default.removeItem(at: ready)
                        return
                    }
                    try await Task.sleep(for: .milliseconds(100))
                }
                throw AppError.timeout
            } catch is CancellationError { }
            catch { stopLocal(); starting = false; self.error = error.localizedDescription }
        }
    }
    private func stopLocal() {
        if let child = backend, child.isRunning { child.terminate() }
        backend = nil
        try? logHandle?.close(); logHandle = nil
        if let readyFile { try? FileManager.default.removeItem(at: readyFile) }
        readyFile = nil
    }
    #endif
}

// Scripts and navigation are scoped to one exact origin / 脚本与页面导航绑定确切 origin。
@MainActor final class WebCoordinator: NSObject, WKNavigationDelegate {
    let connection: Connection
    var failure: (String) -> Void
    init(_ connection: Connection, failure: @escaping (String) -> Void) {
        self.connection = connection; self.failure = failure
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url,
              let source = URLComponents(string: connection.url),
              url.scheme == source.scheme, url.host == source.host, url.port == source.port,
              navigationAction.targetFrame?.isMainFrame != false else {
            decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        failure("服务不可用：" + error.localizedDescription)
    }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        failure("页面加载失败：" + error.localizedDescription)
    }
}

@MainActor func configuredWebView(_ connection: Connection, coordinator: WebCoordinator) -> WKWebView {
    let configuration = WKWebViewConfiguration()
    configuration.websiteDataStore = .nonPersistent()
    let payload: [String: String] = ["origin": connection.url, "actor": connection.actor_id, "token": connection.token]
    let data = try! JSONSerialization.data(withJSONObject: payload)
    let json = String(decoding: data, as: UTF8.self)
    let script = """
    (() => { const c = \(json); if (window.location.origin !== c.origin) return;
    localStorage.setItem('living-agent.actor-id', c.actor);
    sessionStorage.setItem('living-agent.management-token', c.token); })();
    """
    configuration.userContentController.addUserScript(WKUserScript(source: script, injectionTime: .atDocumentStart, forMainFrameOnly: true))
    let view = WKWebView(frame: .zero, configuration: configuration)
    view.navigationDelegate = coordinator
    view.allowsBackForwardNavigationGestures = true
    #if os(iOS)
    view.scrollView.keyboardDismissMode = .interactive
    #endif
    view.load(URLRequest(url: connection.studio))
    return view
}

#if os(macOS)
struct StudioWebView: NSViewRepresentable {
    let connection: Connection
    let failure: (String) -> Void
    func makeCoordinator() -> WebCoordinator { WebCoordinator(connection, failure: failure) }
    func makeNSView(context: Context) -> WKWebView { configuredWebView(connection, coordinator: context.coordinator) }
    func updateNSView(_ view: WKWebView, context: Context) { }
}
#else
struct StudioWebView: UIViewRepresentable {
    let connection: Connection
    let failure: (String) -> Void
    func makeCoordinator() -> WebCoordinator { WebCoordinator(connection, failure: failure) }
    func makeUIView(context: Context) -> WKWebView { configuredWebView(connection, coordinator: context.coordinator) }
    func updateUIView(_ view: WKWebView, context: Context) { }
}
#endif

extension View {
    @ViewBuilder func credentialInput() -> some View {
        #if os(iOS)
        self.textInputAutocapitalization(.never).autocorrectionDisabled()
        #else
        self
        #endif
    }
}

struct ConnectionSettings: View {
    @ObservedObject var model: AppModel
    var body: some View {
        NavigationStack {
            Form {
                Section("连接 Agent 服务") {
                    TextField("https://agent.example.com", text: $model.serverURL).credentialInput().accessibilityIdentifier("connection-url")
                    TextField("所有者 ID", text: $model.actorID).credentialInput().accessibilityIdentifier("connection-actor")
                    SecureField("管理令牌", text: $model.token).credentialInput().accessibilityIdentifier("connection-token")
                    Text("iPhone 连接桌面或服务器上的 Agent。聊天和群聊记录保存在服务端。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                if let error = model.error { Text(error).foregroundStyle(.red) }
                Button("连接并保存到钥匙串") { model.connectRemote() }.disabled(model.starting)
                #if os(macOS)
                Button("使用本机 Agent") { model.startLocal() }
                #endif
                if model.connection != nil { Button("断开连接", role: .destructive) { model.disconnect() } }
            }
            .formStyle(.grouped)
            .navigationTitle("连接设置")
            .toolbar { if model.connection != nil { Button("完成") { model.showSettings = false } } }
        }
        #if os(macOS)
        .frame(minWidth: 440, minHeight: 380)
        #endif
    }
}

struct MainView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Image(systemName: "sparkles").foregroundStyle(.green)
                Text("LivingAgent").font(.headline)
                Spacer()
                Button { model.showSettings = true } label: { Image(systemName: "gearshape") }
                    .accessibilityLabel("连接设置")
            }.padding(12)
            Divider()
            if let connection = model.connection {
                if let error = model.error {
                    HStack { Text(error).font(.footnote); Button("重试") { model.error = nil; model.reloadID = UUID() } }.padding(8)
                }
                StudioWebView(connection: connection, failure: { model.error = $0 }).id(connection).id(model.reloadID)
            } else {
                VStack(spacing: 18) {
                    Image(systemName: "person.3.sequence.fill").font(.system(size: 56)).foregroundStyle(.green)
                    Text(model.starting ? "正在启动 Agent…" : "与 Agent 相伴，也与更多角色交流").font(.title3)
                    if model.starting { ProgressView() }
                    if let error = model.error { Text(error).foregroundStyle(.red).multilineTextAlignment(.center) }
                    Button("连接设置") { model.showSettings = true }
                    #if os(macOS)
                    if !model.starting { Button("启动本机 Agent") { model.startLocal() } }
                    #endif
                }.padding(28).frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .sheet(isPresented: $model.showSettings) { ConnectionSettings(model: model) }
        #if os(macOS)
        .frame(minWidth: 820, minHeight: 600)
        #endif
    }
}

@main struct LivingAgentApp: App {
    @StateObject private var model = AppModel()
    var body: some Scene {
        WindowGroup { MainView(model: model) }
        #if os(macOS)
        .defaultSize(width: 1180, height: 820)
        .commands { CommandGroup(replacing: .newItem) { } }
        #endif
    }
}
