import Foundation
import Security

struct GenesisCourse: Codable, Identifiable {
    var id: String
    var label: String
    var canvas_id: String
    var aliases: [String]?        // extra words notes use for this class ("calc", a professor's name)
    var language: String?         // a CS class's programming language, when it has one
}

/// A plugin is a place Genesis gathers what it needs for your brief: assignments, documents,
/// dates, announcements. Like adding a connector to ChatGPT or Claude: off until you add it,
/// and if you don't, it never runs or collects anything. (The companion and iPhone notes are
/// part of Genesis itself, not plugins: notes from the phone just start working the first
/// time one arrives.)
struct GenesisPlugin: Identifiable {
    let id: String
    let name: String
    let symbol: String
    let summary: String
    let detail: String
    var suggested = false

    static let catalog: [GenesisPlugin] = [
        GenesisPlugin(id: "canvas", name: "Canvas", symbol: "graduationcap",
                      summary: "Your classes, assignments, files and grades.",
                      detail: "Works with any school that uses Canvas. Sign in like you always do, or use an access token if your school allows one. Read-only: Genesis never submits or changes anything.", suggested: true),
        GenesisPlugin(id: "calendar", name: "Calendar", symbol: "calendar",
                      summary: "Every due date on your Canvas calendar.",
                      detail: "Genesis picks up your private Canvas calendar feed for you, so dates that only live on the calendar never slip by. The link stays in your Keychain.", suggested: true),
        GenesisPlugin(id: "email", name: "School email", symbol: "envelope",
                      summary: "What professors only send by email.",
                      detail: "Reads emails from Canvas and your school so nothing announced only by email gets missed. Read-only: nothing is marked read, sent or deleted."),
    ]
}

struct GenesisConfiguration: Codable {
    var courses: [GenesisCourse] = []
    var codex_path: String = ""
    var plugins: [String: Bool] = [:]
    var plugins_chosen: Bool = false        // the first-launch setup has been answered
    var welcomed: Bool = false              // you've met Genesis (the black-window welcome)
    var cop3330_professor_enabled: Bool?
    var canvas_host: String = ""            // your school's Canvas address, e.g. canvas.myschool.edu
    var canvas_auth: String = "signin"      // "signin" (your normal login) or "token" (an access token)
    var school_email: String?
    var timezone: String?
    var public_resource_hosts: [String]?

    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        courses = try c.decodeIfPresent([GenesisCourse].self, forKey: .courses) ?? []
        codex_path = try c.decodeIfPresent(String.self, forKey: .codex_path) ?? ""
        plugins = try c.decodeIfPresent([String: Bool].self, forKey: .plugins) ?? [:]
        plugins_chosen = try c.decodeIfPresent(Bool.self, forKey: .plugins_chosen) ?? false
        welcomed = try c.decodeIfPresent(Bool.self, forKey: .welcomed) ?? false
        cop3330_professor_enabled = try c.decodeIfPresent(Bool.self, forKey: .cop3330_professor_enabled)
        canvas_host = try c.decodeIfPresent(String.self, forKey: .canvas_host) ?? ""
        canvas_auth = try c.decodeIfPresent(String.self, forKey: .canvas_auth) ?? "signin"
        school_email = try c.decodeIfPresent(String.self, forKey: .school_email)
        timezone = try c.decodeIfPresent(String.self, forKey: .timezone)
        public_resource_hosts = try c.decodeIfPresent([String].self, forKey: .public_resource_hosts)
    }

    func on(_ plugin: String) -> Bool {
        plugins[plugin] == true || (plugin == "professor_sites" && cop3330_professor_enabled == true)
    }

    static func url(root: String) -> URL {
        URL(fileURLWithPath: root).appendingPathComponent("outputs/School HQ Study/connections.json")
    }
    static func load(root: String) throws -> Self {
        let file = url(root: root)
        guard FileManager.default.fileExists(atPath: file.path) else { return Self() }
        let value = try JSONDecoder().decode(Self.self, from: Data(contentsOf: file))
        try value.validate()
        return value
    }
    func validate() throws {
        guard courses.count <= 30, Set(courses.map(\.id)).count == courses.count,
              Set(courses.map(\.canvas_id)).count == courses.count,
              courses.allSatisfy({ $0.id.range(of: "^[A-Za-z0-9][A-Za-z0-9_-]{1,39}$", options: .regularExpression) != nil &&
                  !$0.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && $0.label.count <= 80 &&
                  $0.canvas_id.range(of: "^[1-9][0-9]{0,19}$", options: .regularExpression) != nil }) else {
            throw NSError(domain: "Genesis", code: 1, userInfo: [NSLocalizedDescriptionKey: "Use a unique class code, a name, and its numeric Canvas course ID."])
        }
    }
    func save(root: String) throws {
        try validate()
        let file = Self.url(root: root)
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        let enc = JSONEncoder(); enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        try enc.encode(self).write(to: file, options: .atomic)
    }
}

enum GenesisLinks {
    /// Where "Get the iPhone app" goes: a page in the public repo that carries the current
    /// TestFlight link, so the link can change without shipping a new Mac build.
    static let iPhoneApp = URL(string: "https://github.com/itwasVega/genesis/blob/main/docs/IPHONE.md")!
}

/// A Canvas access token, for schools that let students make one. Kept in the Keychain, never in files.
enum CanvasToken {
    static let service = "Genesis.Canvas.Token.v1"
    static func read(host: String) -> String? {
        guard !host.isEmpty else { return nil }
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: host, kSecReturnData as String: true]
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        let t = String(decoding: d, as: UTF8.self)
        return t.isEmpty ? nil : t
    }
    @discardableResult
    static func save(_ token: String, host: String) -> Bool {
        let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: host]
        SecItemDelete(base as CFDictionary)
        var item = base
        item[kSecValueData as String] = Data(token.utf8)
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        return SecItemAdd(item as CFDictionary, nil) == errSecSuccess
    }
    static func remove(host: String) {
        SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: host] as CFDictionary)
    }
}

/// Turns whatever a student pastes or types ("canvas.myschool.edu", a full Canvas link,
/// "https://myschool.instructure.com/courses/123") into the bare Canvas host.
enum CanvasAddress {
    static func host(from typed: String) -> String? {
        var t = typed.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if t.isEmpty { return nil }
        if !t.contains("://") { t = "https://" + t }
        guard let h = URL(string: t)?.host, h.range(of: "^[a-z0-9.-]+\\.[a-z]{2,}$", options: .regularExpression) != nil else { return nil }
        return h
    }
}
