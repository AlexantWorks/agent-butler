import Cocoa
import WebKit

/// 无边框 NSPanel 默认不能成 key window → 中文输入法挂不上。放行。
final class KeyablePanel: NSPanel {
    override var canBecomeKey: Bool { true }
}

/// WKWebView 默认吃掉背景拖动;放行后 mini 整卡可拖(按钮点击不受影响)。
final class DraggableWebView: WKWebView {
    override var mouseDownCanMoveWindow: Bool { true }
}

/// HTML 里 fetch("/api/ui",...) 拦截转发到原生(零 server 往返、零文件桥)。
private let uiBridgeJS = """
(function(){
  const _f = window.fetch;
  window.fetch = function(u, opt){
    if (typeof u === 'string' && u.indexOf('/api/ui') === 0 && opt && opt.body) {
      try { window.webkit.messageHandlers.butler.postMessage(JSON.parse(opt.body)); } catch(e){}
      return Promise.resolve(new Response('{"ok":true}', {status:200}));
    }
    return _f.apply(this, arguments);
  };
})();
"""

/// 浮窗(F12) + mini 桌面看板(F13) 的生命周期/定位/持久化/命令桥。
final class PanelManager: NSObject, WKScriptMessageHandler {
    private var popover: KeyablePanel?
    private var popoverWV: WKWebView?
    private var mini: KeyablePanel?
    private var miniWV: WKWebView?
    private var clickMonitor: Any?
    private var lastAutoHide = Date.distantPast   // 外部点击(含点徽标)自动关闭的时刻

    /// 页面按钮命令回调 → AppDelegate 执行。
    var onCommand: ((String, Bool) -> Void)?

    private let popW: CGFloat = 380, popH: CGFloat = 560
    private let miniW: CGFloat = 240, miniH: CGFloat = 190

    override init() {
        super.init()
        if UserDefaults.standard.bool(forKey: "mini_on") { showMini() }
    }

    // MARK: webview 工厂
    private func makeWebView(path: String, frame: NSRect, draggable: Bool) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        let ucc = WKUserContentController()
        ucc.add(self, name: "butler")
        ucc.addUserScript(WKUserScript(source: uiBridgeJS, injectionTime: .atDocumentStart,
                                       forMainFrameOnly: true))
        cfg.userContentController = ucc
        let cls: WKWebView.Type = draggable ? DraggableWebView.self : WKWebView.self
        let wv = cls.init(frame: frame, configuration: cfg)
        wv.setValue(false, forKey: "drawsBackground")     // 透明角落不发白
        if let url = URL(string: Butler.baseURL + path) {
            wv.load(URLRequest(url: url))
        }
        return wv
    }

    private func makePanel(size: NSSize) -> KeyablePanel {
        let p = KeyablePanel(contentRect: NSRect(origin: .zero, size: size),
                             styleMask: [.borderless, .nonactivatingPanel],
                             backing: .buffered, defer: false)
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = true
        p.collectionBehavior = [.canJoinAllSpaces, .stationary]
        return p
    }

    // MARK: 浮窗
    /// anchor = 菜单栏图标窗口的屏幕 frame。
    func togglePopover(anchor: NSRect) {
        if let p = popover, p.isVisible { hidePopover(); return }
        // 点徽标关闭浮窗时:全局监听器已在 mouseDown 关掉它,这里的 mouseUp 别再重开
        if Date().timeIntervalSince(lastAutoHide) < 0.35 { return }
        if popover == nil {
            let f = NSRect(x: 0, y: 0, width: popW, height: popH)
            let wv = makeWebView(path: "/popover", frame: f, draggable: false)
            let p = makePanel(size: f.size)
            p.contentView = wv
            p.level = .floating          // 高于普通窗、低于输入法候选窗(Status 层会盖候选窗)
            popover = p; popoverWV = wv
        } else {
            popoverWV?.reload()          // 每次打开都是新鲜数据
        }
        guard let p = popover, let screen = NSScreen.main?.visibleFrame else { return }
        var x = anchor.midX - popW / 2
        x = max(screen.minX + 8, min(x, screen.maxX - popW - 8))
        let top = anchor.minY - 6
        p.setFrameTopLeftPoint(NSPoint(x: x, y: top))
        p.makeKeyAndOrderFront(nil)
        armOutsideClick()
    }

    func hidePopover() {
        popover?.orderOut(nil)
        disarmOutsideClick()
    }

    private func armOutsideClick() {
        disarmOutsideClick()
        clickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            self?.lastAutoHide = Date()
            self?.hidePopover()
        }
    }
    private func disarmOutsideClick() {
        if let m = clickMonitor { NSEvent.removeMonitor(m); clickMonitor = nil }
    }

    // MARK: mini
    func showMini() {
        if let m = mini, m.isVisible { return }
        if mini == nil {
            let f = NSRect(x: 0, y: 0, width: miniW, height: miniH)
            let wv = makeWebView(path: "/mini", frame: f, draggable: true)
            let p = makePanel(size: f.size)
            p.contentView = wv
            p.isMovableByWindowBackground = true
            p.setFrameAutosaveName("ButlerMini")          // 位置持久化(原生)
            mini = p; miniWV = wv
        }
        applyMiniLevel(UserDefaults.standard.bool(forKey: "mini_top"))
        if mini?.setFrameUsingName("ButlerMini") != true, let screen = NSScreen.main?.visibleFrame {
            mini?.setFrameTopLeftPoint(NSPoint(x: screen.maxX - miniW - 24, y: screen.maxY - 24))
        }
        mini?.orderFront(nil)
        UserDefaults.standard.set(true, forKey: "mini_on")
    }

    func hideMini() {
        mini?.orderOut(nil)
        UserDefaults.standard.set(false, forKey: "mini_on")
    }

    var miniVisible: Bool { mini?.isVisible ?? false }
    func toggleMini() { miniVisible ? hideMini() : showMini() }

    func setMiniTop(_ top: Bool) {
        UserDefaults.standard.set(top, forKey: "mini_top")
        if mini != nil { applyMiniLevel(top) }
    }

    private func applyMiniLevel(_ top: Bool) {
        // 贴桌面层 = 桌面图标之上、普通窗口之下
        let desktopIcon = CGWindowLevelForKey(.desktopIconWindow) + 1
        mini?.level = top ? .floating : NSWindow.Level(rawValue: Int(desktopIcon))
    }

    // MARK: WKScriptMessageHandler — 页面按钮 → 原生命令
    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], let cmd = body["cmd"] as? String else { return }
        let top = body["top"] as? Bool ?? false
        onCommand?(cmd, top)
    }
}
