import Cocoa
import UserNotifications

/// 原生系统通知 — 图标天然=app 自己的图标(不可配置,永远正确;告别 terminal-notifier)。
/// running→waiting 跳变即"该你了";武装模型防轰炸;每日搁置(等你>24h)摘要。
final class Notifier: NSObject, UNUserNotificationCenterDelegate {
    private var prevStatus: [String: String]?      // nil = 尚未首刷
    private var armed: [String: Bool] = [:]
    private var digestDay = ""

    func requestAuth() {
        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    // app 在前台时也允许横幅(菜单栏 app 无窗口焦点,不弹会漏)
    func userNotificationCenter(_ c: UNUserNotificationCenter,
                               willPresent n: UNNotification,
                               withCompletionHandler h: @escaping (UNNotificationPresentationOptions) -> Void) {
        h([.banner, .sound])
    }

    // 点击通知 → 打开完整看板
    func userNotificationCenter(_ c: UNUserNotificationCenter,
                               didReceive r: UNNotificationResponse,
                               withCompletionHandler h: @escaping () -> Void) {
        NotificationCenter.default.post(name: .butlerOpenBoard, object: nil)
        h()
    }

    private func send(title: String, subtitle: String, body: String, sound: Bool) {
        let c = UNMutableNotificationContent()
        c.title = title
        if !subtitle.isEmpty { c.subtitle = subtitle }
        c.body = body
        if sound { c.sound = .default }
        let req = UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil)
        UNUserNotificationCenter.current().add(req, withCompletionHandler: nil)
    }

    private func trunc(_ s: String?, _ n: Int) -> String {
        let t = (s ?? "").replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return t.count <= n ? t : String(t.prefix(n - 1)) + "…"
    }

    /// 每次数据刷新调用 — 检测跳变发通知。
    func checkTransitions(_ cards: [Card]) {
        let cur = Dictionary(cards.map { ($0.id, $0.status) }, uniquingKeysWith: { a, _ in a })
        guard let prev = prevStatus else {
            prevStatus = cur                       // 首刷只登记,不对存量 waiting 补发
            for c in cards { armed[c.id] = (c.status == "running") }
            return
        }
        for c in cards {
            let was = prev[c.id]
            if c.status == "running" {
                armed[c.id] = true                 // 回到跑着 → 重新武装
            } else if c.status == "waiting", was == "running", armed[c.id] ?? true {
                armed[c.id] = false
                let sub = L10n.t("Your turn") + (c.engine == "codex" ? " · Codex" : "")
                var body = trunc(c.activity, 60)
                if body.isEmpty { body = trunc(c.note, 60) }
                if body.isEmpty { body = L10n.t("The agent finished and is waiting for your next step.") }
                send(title: trunc(c.displayName, 30), subtitle: sub, body: body, sound: true)
            }
        }
        prevStatus = cur
        idleDigest(cards)
    }

    /// 每日 10 点后首刷:等你 >24h 的汇总一条(无声);手动搁置=主动决定不提醒。
    private func idleDigest(_ cards: [Card]) {
        let now = Date()
        let cal = Calendar.current
        let comp = cal.dateComponents([.year, .month, .day, .hour], from: now)
        let today = "\(comp.year ?? 0)-\(comp.month ?? 0)-\(comp.day ?? 0)"
        guard (comp.hour ?? 0) >= 10, digestDay != today else { return }
        digestDay = today
        let stale = cards.filter { $0.status == "waiting" && ($0.age ?? 0) > 86400 }
        guard !stale.isEmpty else { return }
        let names = stale.prefix(2).map { trunc($0.displayName, 16) }
        var body = names.joined(separator: " · ")
        if stale.count > 2 {
            body += " · " + String(format: L10n.t("%d more"), stale.count - 2)
        }
        send(title: String(format: L10n.t("%d sessions waiting for over 24 hours"), stale.count),
             subtitle: "", body: body, sound: false)
    }
}

extension Notification.Name {
    static let butlerOpenBoard = Notification.Name("butlerOpenBoard")
}
