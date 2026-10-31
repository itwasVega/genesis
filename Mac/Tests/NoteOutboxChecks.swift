import Foundation

@main struct NoteOutboxChecks {
    static func main() throws {
        let fm = FileManager.default
        let base = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? fm.removeItem(at: base) }
        let outbox = NoteOutbox(directory: base.appendingPathComponent("Outbox"))
        try outbox.save(["id":"one", "course":"TEST101", "text":"Keep this"], id: "one")
        try Data("broken".utf8).write(to: outbox.directory.appendingPathComponent("invalid.json"))
        let url = try outbox.shortcutURL(name: "Genesis Note")!
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)!.queryItems!
        let callback = URL(string: query.first { $0.name == "x-success" }!.value!)!
        let invalid = URL(string: "genesis-pocket://sent?nonce=wrong")!
        precondition(tryResult(outbox, invalid) == nil)
        let before = try outbox.files()
        precondition(before.count == 2)
        try outbox.save(["id":"two", "course":"TEST101", "text":"Newer note"], id: "two")
        let restarted = NoteOutbox(directory: outbox.directory)
        precondition(tryResult(restarted, callback) == "sent")
        let remaining = try restarted.files()
        precondition(remaining.count == 2 && remaining.contains { $0.lastPathComponent == "invalid.json" })
        precondition(tryResult(restarted, callback) == nil)
        let backup = try fm.contentsOfDirectory(at: base.appendingPathComponent("Delivered"), includingPropertiesForKeys: nil)
        precondition(backup.count == 1)
        let occupied = base.appendingPathComponent("not-a-directory")
        try Data("occupied".utf8).write(to: occupied)
        var rejected = false
        do { try NoteOutbox(directory: occupied).save(["id":"three"], id: "three") } catch { rejected = true }
        precondition(rejected)
        print("PASS: save failures surface; invalid/replayed callbacks preserve notes; restart acknowledges only serialized notes and retains recovery copies.")
    }
    static func tryResult(_ store: NoteOutbox, _ url: URL) -> String? { try? store.handle(url) }
}
