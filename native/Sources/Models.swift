import Foundation

/// 一张会话卡片 — 与 server.py build_cards() 输出对齐(只解码 Swift 侧需要的字段)。
struct Card: Decodable {
    let id: String
    let status: String            // running / waiting / idle
    let task: String?
    let title_app: String?
    let title_ov: String?
    let note: String?
    let priority: String?
    let activity: String?
    let ago: String?
    let engine: String?
    let age: Double?

    var displayName: String {
        if let t = title_ov, !t.isEmpty { return t }
        if let t = title_app, !t.isEmpty { return t }
        return task ?? L10n.t("Untitled Session")
    }
}

struct SessionsResponse: Decodable {
    let cards: [Card]
    let demo: Bool?
}

enum Butler {
    static let port = 7788
    static var baseURL: String { "http://127.0.0.1:\(port)" }
}
