import Foundation

struct GenesisCourse: Codable, Identifiable {
    var id: String
    var label: String
    var canvas_id: String
}

/// A plugin: something Genesis can use only after you pick it. Like adding a connector to
/// ChatGPT or Claude: if you don't need it, it never runs, collects or appears.
struct GenesisPlugin: Identifiable {
    let id: String
    let name: String
    let symbol: String
    let summary: String
    let detail: String
    var suggested = false

    static let catalog: [GenesisPlugin] = [
        GenesisPlugin(id: "canvas", name: "Canvas", symbol: "graduationcap",
                      summary: "Builds your plan from your classes.",
                      detail: "Reads assignments, announcements, files and grades from UCF Webcourses through Genesis's own browser, read-only.", suggested: true),
        GenesisPlugin(id: "iphone", name: "iPhone notes", symbol: "iphone",
                      summary: "Rapid-fire notes from your phone.",
                      detail: "\"Missed class\", \"test moved to Friday\", \"quiz covers 4.2\": send notes from the Genesis iPhone app and your plan reshapes around them. Uses a folder in iCloud Drive."),
        GenesisPlugin(id: "calendar", name: "Calendar", symbol: "calendar",
                      summary: "Due dates from your Webcourses calendar.",
                      detail: "Adds your private Webcourses calendar feed, for dates that only show up there. The link is stored in your Keychain."),
        GenesisPlugin(id: "email", name: "Email", symbol: "envelope",
                      summary: "Course emails in Library.",
                      detail: "Makes Canvas and school emails searchable in Library. Read-only: nothing is marked read or changed. Uses an app password stored in your Keychain."),
        GenesisPlugin(id: "professor_sites", name: "Professor websites", symbol: "globe",
                      summary: "Public course pages outside Canvas.",
                      detail: "Some professors post slides and notes on their own websites. Genesis checks the public pages it knows about."),
    ]
}

struct GenesisConfiguration: Codable {
    var courses: [GenesisCourse] = []
    var codex_path: String = ""
    var plugins: [String: Bool] = [:]
    var plugins_chosen: Bool = false        // the first-launch picker has been answered
    var cop3330_professor_enabled: Bool?

    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        courses = try c.decodeIfPresent([GenesisCourse].self, forKey: .courses) ?? []
        codex_path = try c.decodeIfPresent(String.self, forKey: .codex_path) ?? ""
        plugins = try c.decodeIfPresent([String: Bool].self, forKey: .plugins) ?? [:]
        plugins_chosen = try c.decodeIfPresent(Bool.self, forKey: .plugins_chosen) ?? false
        cop3330_professor_enabled = try c.decodeIfPresent(Bool.self, forKey: .cop3330_professor_enabled)
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
