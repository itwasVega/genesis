import Foundation

@main
struct RuntimeStorageChecks {
    static func main() throws {
        let fm = FileManager.default
        let base = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
            .appendingPathComponent(UUID().uuidString)
        defer { try? fm.removeItem(at: base) }
        let template = base.appendingPathComponent("template")
        let root = base.appendingPathComponent("workspace")
        let outputs = template.appendingPathComponent("outputs")
        try fm.createDirectory(at: outputs, withIntermediateDirectories: true)
        let script = outputs.appendingPathComponent("genesis_app_bridge.py")
        try Data("version one".utf8).write(to: script)
        try Data("default".utf8).write(to: outputs.appendingPathComponent("genesis_models.json"))
        try GenesisRuntime.installTemplate(from: template, into: root)
        let target = root.appendingPathComponent("outputs/genesis_app_bridge.py")
        precondition(tryString(target) == "version one")
        let record = root.appendingPathComponent("outputs/Genesis App/Bridge/user-record.json")
        try Data("preserve this".utf8).write(to: record)
        let models = root.appendingPathComponent("outputs/genesis_models.json")
        try Data("custom".utf8).write(to: models)
        try Data("version two".utf8).write(to: script)
        try GenesisRuntime.installTemplate(from: template, into: root)
        precondition(tryString(target) == "version two")
        precondition(tryString(record) == "preserve this")
        precondition(tryString(models) == "custom")
        let backups = fm.enumerator(at: root.appendingPathComponent("Genesis Code Backups"), includingPropertiesForKeys: nil)!
        let saved = backups.allObjects.compactMap { $0 as? URL }.filter { $0.lastPathComponent == "genesis_app_bridge.py" }
        precondition(saved.count == 1 && tryString(saved[0]) == "version one")
        let outside = base.appendingPathComponent("outside")
        try Data("unchanged".utf8).write(to: outside)
        try fm.removeItem(at: target)
        try fm.createSymbolicLink(at: target, withDestinationURL: outside)
        var rejected = false
        do { try GenesisRuntime.installTemplate(from: template, into: root) }
        catch { rejected = true }
        precondition(rejected && tryString(outside) == "unchanged")
        print("PASS: fresh workspace initializes; code updates preserve records and model settings; symlink destinations are refused.")
    }
    static func tryString(_ url: URL) -> String { (try? String(contentsOf: url, encoding: .utf8)) ?? "" }
}
