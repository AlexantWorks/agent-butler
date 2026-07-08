import Cocoa
import WebKit
import ServiceManagement

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var server: ServerManager!
    private let panels = PanelManager()
    private let notifier = Notifier()
    private var boardWindow: NSWindow?
    private var refreshTimer: Timer?
    private var demoFlagPath: String {
        NSString(string: "~/.claude-monitor/demo-mode").expandingTildeInPath
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        // server.py 在 app bundle 的 Resources 里(打包);开发期回落到 repo 根
        let bundled = Bundle.main.resourceURL?.appendingPathComponent("server.py").path
        let devPath = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("server.py").path
        let script = (bundled.flatMap { FileManager.default.fileExists(atPath: $0) ? $0 : nil }) ?? devPath
        server = ServerManager(scriptPath: script)
        server.ensureRunning()

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "▦"
        statusItem.button?.target = self
        statusItem.button?.action = #selector(statusClicked)
        statusItem.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])

        panels.onCommand = { [weak self] cmd, top in self?.handle(cmd: cmd, top: top) }
        notifier.requestAuth()
        NotificationCenter.default.addObserver(self, selector: #selector(openBoard),
                                               name: .butlerOpenBoard, object: nil)
        syncUIState()

        refreshTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.refresh()
        }
        refreshTimer?.tolerance = 1
        refresh()
    }

    func applicationWillTerminate(_ note: Notification) { server?.stop() }

    // MARK: 数据刷新 → 徽标 + 通知 + server 自愈
    private func refresh() {
        server.keepAlive()          // 后台保活,不阻塞主线程(旧版每5s主线程同步健康检查=点击被吞)
        guard let url = URL(string: Butler.baseURL + "/api/sessions") else { return }
        var req = URLRequest(url: url); req.timeoutInterval = 4
        req.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: req) { [weak self] data, _, _ in
            guard let self, let data,
                  let resp = try? JSONDecoder().decode(SessionsResponse.self, from: data) else { return }
            DispatchQueue.main.async {
                let cards = resp.cards
                let waiting = cards.filter { $0.status == "waiting" }.count
                let running = cards.filter { $0.status == "running" }.count
                self.statusItem.button?.title = waiting > 0 ? "▦ \(waiting)" : (running > 0 ? "▦ ·" : "▦")
                if resp.demo != true {
                    self.notifier.checkTransitions(cards)
                }
            }
        }.resume()
    }

    // MARK: 菜单栏点击 — 左键浮窗 / 右键备份菜单
    @objc private func statusClicked() {
        if NSApp.currentEvent?.type == .rightMouseUp {
            showBackupMenu()
            return
        }
        if let win = statusItem.button?.window {
            panels.togglePopover(anchor: win.frame)
        }
    }

    private func showBackupMenu() {
        let menu = NSMenu()
        menu.addItem(withTitle: L10n.t("Open Full Board"), action: #selector(openBoard), keyEquivalent: "")
        menu.addItem(withTitle: panels.miniVisible ? L10n.t("Hide Desktop Mini Board") : L10n.t("Show Desktop Mini Board"),
                     action: #selector(toggleMiniMenu), keyEquivalent: "")
        let demo = menu.addItem(withTitle: L10n.t("Demo Mode"), action: #selector(toggleDemoMode), keyEquivalent: "")
        demo.state = isDemoMode ? .on : .off
        menu.addItem(.separator())
        let auto = menu.addItem(withTitle: L10n.t("Launch at Login"), action: #selector(toggleAutostart), keyEquivalent: "")
        auto.state = (SMAppService.mainApp.status == .enabled) ? .on : .off
        menu.addItem(.separator())
        menu.addItem(withTitle: L10n.t("Quit Butler"), action: #selector(quit), keyEquivalent: "q")
        for item in menu.items { item.target = self }
        statusItem.menu = menu
        statusItem.button?.performClick(nil)
        statusItem.menu = nil                    // 弹完摘掉,恢复左键浮窗
    }

    // MARK: 页面/菜单命令
    private func handle(cmd: String, top: Bool) {
        switch cmd {
        case "board":     panels.hidePopover(); openBoard()
        case "mini":      panels.toggleMini(); syncUIState()
        case "minitop":   panels.setMiniTop(top); syncUIState()
        case "hidepop":   panels.hidePopover()
        case "autostart": toggleAutostart()
        case "quit":      quit()
        default: break
        }
    }

    @objc private func toggleMiniMenu() { panels.toggleMini(); syncUIState() }

    private var isDemoMode: Bool {
        FileManager.default.fileExists(atPath: demoFlagPath)
    }

    @objc private func toggleDemoMode() {
        let dir = NSString(string: "~/.claude-monitor").expandingTildeInPath
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        if isDemoMode {
            try? FileManager.default.removeItem(atPath: demoFlagPath)
        } else {
            FileManager.default.createFile(atPath: demoFlagPath, contents: Data())
        }
        syncUIState()
        refresh()
    }

    @objc private func toggleAutostart() {
        do {
            if SMAppService.mainApp.status == .enabled {
                try SMAppService.mainApp.unregister()
            } else {
                try SMAppService.mainApp.register()
            }
        } catch { NSLog("Butler: \(L10n.t("Login item toggle failed")) \(error)") }
        syncUIState()
    }

    // 把 mini/autostart 状态写给 server.py(供 /api/uistate 给 HTML toggle 用)
    private func syncUIState() {
        let dir = NSString(string: "~/.claude-monitor").expandingTildeInPath
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        let state: [String: Any] = [
            "mini_on": panels.miniVisible,
            "mini_top": UserDefaults.standard.bool(forKey: "mini_top"),
            "autostart": SMAppService.mainApp.status == .enabled,
            "demo": isDemoMode,
        ]
        if let data = try? JSONSerialization.data(withJSONObject: state) {
            try? data.write(to: URL(fileURLWithPath: dir + "/ui-state.json"))
        }
    }

    // MARK: 完整看板窗口(原生 WKWebView,替代 pywebview)
    @objc private func openBoard() {
        if let w = boardWindow { w.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true); return }
        let wv = WKWebView(frame: NSRect(x: 0, y: 0, width: 1120, height: 780))
        if let url = URL(string: Butler.baseURL + "/") { wv.load(URLRequest(url: url)) }
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1120, height: 780),
                         styleMask: [.titled, .closable, .miniaturizable, .resizable],
                         backing: .buffered, defer: false)
        w.title = L10n.t("Butler")
        w.contentView = wv
        w.center()
        w.setFrameAutosaveName("ButlerBoard")
        w.isReleasedWhenClosed = false
        boardWindow = w
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func quit() { server?.stop(); NSApp.terminate(nil) }
}
