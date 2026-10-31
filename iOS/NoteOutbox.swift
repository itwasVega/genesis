import Foundation

/// Durable delivery state, independent of UI and iCloud permissions.
final class NoteOutbox {
    struct Pending: Codable { var nonce: String; var files: [String] }
    let directory: URL
    private let pendingFile: URL
    private let delivered: URL
    private let fm = FileManager.default

    init(directory: URL) {
        self.directory = directory
        pendingFile = directory.deletingLastPathComponent().appendingPathComponent("PendingShortcut.json")
        delivered = directory.deletingLastPathComponent().appendingPathComponent("Delivered")
    }

    func files() throws -> [URL] {
        try fm.createDirectory(at: directory, withIntermediateDirectories: true)
        return try fm.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    func save<T: Encodable>(_ note: T, id: String) throws {
        try fm.createDirectory(at: directory, withIntermediateDirectories: true)
        let name = String(format: "%.3f", Date().timeIntervalSince1970) + "-" + id + ".json"
        try JSONEncoder().encode(note).write(to: directory.appendingPathComponent(name), options: .atomic)
    }

    func shortcutURL(name: String) throws -> URL? {
        var notes: [[String: Any]] = [], sent: [String] = []
        for file in try files() {
            // Keep malformed notes for recovery; never acknowledge something we didn't send.
            guard let data = try? Data(contentsOf: file),
                  let note = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  note["id"] is String, note["course"] is String, note["text"] is String else { continue }
            let candidate = notes + [note]
            let bytes = try JSONSerialization.data(withJSONObject: candidate)
            // Bound URL size. Remaining notes are sent by the next explicit delivery.
            if bytes.count > 24_000 { break }
            notes = candidate; sent.append(file.lastPathComponent)
        }
        guard !notes.isEmpty else {
            if try !files().isEmpty { throw CocoaError(.fileReadCorruptFile) }
            return nil
        }
        let nonce = UUID().uuidString.lowercased()
        let json = String(decoding: try JSONSerialization.data(withJSONObject: notes), as: UTF8.self)
        var components = URLComponents(string: "shortcuts://x-callback-url/run-shortcut")!
        components.queryItems = [URLQueryItem(name: "name", value: name), URLQueryItem(name: "input", value: "text"), URLQueryItem(name: "text", value: json)]
        for (key, host) in [("x-success", "sent"), ("x-cancel", "cancel"), ("x-error", "error")] {
            components.queryItems?.append(URLQueryItem(name: key, value: "genesis-pocket://\(host)?nonce=\(nonce)"))
        }
        guard let url = components.url else { throw CocoaError(.fileWriteUnknown) }
        try JSONEncoder().encode(Pending(nonce: nonce, files: sent)).write(to: pendingFile, options: .atomic)
        return url
    }

    /// A callback only acknowledges its exact persisted batch. Retain a recovery copy.
    func handle(_ url: URL) throws -> String? {
        guard url.scheme == "genesis-pocket", let host = url.host,
              ["sent", "cancel", "error"].contains(host), url.path.isEmpty,
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems,
              items.filter({ $0.name == "nonce" }).count == 1,
              let nonce = items.first(where: { $0.name == "nonce" })?.value,
              let data = try? Data(contentsOf: pendingFile),
              let pending = try? JSONDecoder().decode(Pending.self, from: data), pending.nonce == nonce else { return nil }
        if host == "sent" {
            try fm.createDirectory(at: delivered, withIntermediateDirectories: true)
            for name in pending.files {
                guard name == URL(fileURLWithPath: name).lastPathComponent else { throw CocoaError(.fileReadCorruptFile) }
                let local = directory.appendingPathComponent(name)
                guard fm.fileExists(atPath: local.path) else { continue }
                let backup = delivered.appendingPathComponent(name)
                // Retrying after an interrupted acknowledgement is idempotent.
                if fm.fileExists(atPath: backup.path) {
                    guard try Data(contentsOf: backup) == Data(contentsOf: local) else { throw CocoaError(.fileWriteFileExists) }
                    try fm.removeItem(at: local)
                } else { try fm.moveItem(at: local, to: backup) }
            }
        }
        try fm.removeItem(at: pendingFile)
        return host
    }
}
