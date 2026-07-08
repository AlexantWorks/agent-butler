import Foundation
import Darwin

/// 托管纯 stdlib 的 server.py 子进程(系统 python3)。
/// 端口被占=复用(校验代码版本);子进程死了自动拉起。
final class ServerManager {
    private var process: Process?
    private let scriptPath: String
    private let logPath = "/tmp/butler-server.log"
    private let q = DispatchQueue(label: "butler.server")   // server 操作串行化,永不碰主线程

    init(scriptPath: String) { self.scriptPath = scriptPath }

    private var appLocale: String {
        Bundle.main.preferredLocalizations.first ?? "en"
    }

    /// 启动时调用一次:可含版本校验(此刻无 UI,阻塞无妨)。
    func ensureRunning() {
        if isPortBusy() {
            if serverIsFresh() { return }          // 复用的 server 是新代码
            killPort()                             // 旧代码 → 换新
            usleep(500_000)
        }
        start()
    }

    /// 周期保活:只在后台串行队列跑,只在 server 真死(端口空)时拉起 —— 不做版本校验、
    /// 不做网络健康检查、不 sleep、绝不阻塞主线程(这是"点击没反应"的根因修复)。
    func keepAlive() {
        q.async { [weak self] in
            guard let self else { return }
            if !self.isPortBusy() { self.start() }
        }
    }

    private func start() {
        guard FileManager.default.fileExists(atPath: scriptPath) else {
            NSLog("Butler: server.py 不存在 \(scriptPath)"); return
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        p.arguments = [scriptPath]
        var env = ProcessInfo.processInfo.environment
        env["BOARD_PORT"] = String(Butler.port)
        env["BUTLER_LOCALE"] = appLocale
        p.environment = env
        if !FileManager.default.fileExists(atPath: logPath) {
            FileManager.default.createFile(atPath: logPath, contents: nil)
        }
        if let fh = FileHandle(forWritingAtPath: logPath) {
            fh.seekToEndOfFile()
            p.standardOutput = fh
            p.standardError = fh
        }
        do { try p.run(); process = p } catch { NSLog("Butler: server 启动失败 \(error)") }
    }

    func stop() { process?.terminate() }

    // 复用前校验:server 报告的源码 mtime ≥ 磁盘上的 → 是新代码
    private func serverIsFresh() -> Bool {
        guard let data = syncGET("/api/health"),
              let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let srcMtime = j["src_mtime"] as? Int else { return false }
        if let serverLocale = j["locale"] as? String, serverLocale != appLocale {
            return false
        }
        let attrs = try? FileManager.default.attributesOfItem(atPath: scriptPath)
        let diskDate = attrs?[.modificationDate] as? Date
        let diskMtime = Int(diskDate?.timeIntervalSince1970 ?? 0)
        return srcMtime >= diskMtime
    }

    func isPortBusy() -> Bool {
        let s = socket(AF_INET, SOCK_STREAM, 0)
        if s < 0 { return false }
        defer { close(s) }
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(Butler.port).bigEndian
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        let r = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(s, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return r == 0
    }

    private func killPort() {
        let t = Process()
        t.executableURL = URL(fileURLWithPath: "/bin/bash")
        t.arguments = ["-c", "kill $(lsof -tiTCP:\(Butler.port) -sTCP:LISTEN) 2>/dev/null"]
        try? t.run(); t.waitUntilExit()
    }

    /// 极简同步 GET(仅用于健康检查,主线程外调用)。
    private func syncGET(_ path: String) -> Data? {
        guard let url = URL(string: Butler.baseURL + path) else { return nil }
        var result: Data?
        let sem = DispatchSemaphore(value: 0)
        var req = URLRequest(url: url); req.timeoutInterval = 2
        URLSession.shared.dataTask(with: req) { d, _, _ in result = d; sem.signal() }.resume()
        _ = sem.wait(timeout: .now() + 3)
        return result
    }
}
