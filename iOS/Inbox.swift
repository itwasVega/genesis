import Foundation
import Observation

/// How notes reach Genesis on the Mac.
///
/// The phone and the Mac share one folder: iCloud Drive/Genesis (the Mac app creates it).
/// Each note is a small JSON file written to Genesis/Notes; the Mac imports it into
/// "Tell Genesis" within a minute while the app is open, and at every sync. The Mac also
/// publishes Genesis/courses.json so the phone shows the same classes.
///
/// Notes are first saved to an outbox inside the app, then moved to iCloud Drive, so a
/// note typed with no connection is never lost; it moves the next time the app opens.
/// Uses a folder you pick once (security-scoped bookmark), so no iCloud entitlement or
/// paid developer account is needed.
struct Course: Codable, Identifiable, Hashable { var id: String; var label: String }

private struct CourseFile: Codable { var courses: [Course] }

struct Note: Codable {
    var id: String
    var course: String
    var text: String
    var created_at: String
    var source = "iphone"
    var session_id: String? = nil      // messages fired off in one go share a session; the Mac combines them
    var seq: Int? = nil
    var session_end: Bool? = nil       // the swipe-down tab: "done for now"
    var count: Int? = nil              // with session_end: how many messages the session holds
}

@MainActor @Observable
final class Inbox {
    static let defaults: [Course] = []

    var courses: [Course] = Inbox.defaults
    private(set) var folderName: String?
    private(set) var waiting = 0          // notes saved on the phone, not yet in iCloud Drive
    var problem: String?

    var connected: Bool { folderName != nil }

    /// True once the "Genesis Note" shortcut has saved a batch successfully.
    var shortcutReady = UserDefaults.standard.bool(forKey: "shortcutReady")
    @ObservationIgnored private lazy var delivery = NoteOutbox(directory: outbox)
    static let shortcutName = "Genesis Note"

    private var folderURL: URL?
    private let outbox = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("Outbox", isDirectory: true)

    init() {
        try? FileManager.default.createDirectory(at: outbox, withIntermediateDirectories: true)
        if let data = UserDefaults.standard.data(forKey: "courses"), let saved = try? JSONDecoder().decode([Course].self, from: data), !saved.isEmpty { courses = saved }
        resolveFolder()
        refresh()
    }

    // MARK: Folder

    // Folder access follows Apple's "Providing access to directories":
    // pick with UIDocumentPickerViewController(forOpeningContentTypes: [.folder]), then
    // startAccessingSecurityScopedResource(), save a .minimalBookmark, resolve it on launch,
    // and use NSFileCoordinator for every read and write.

    private var bookmarkFile: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("genesis-folder.bookmark")
    }

    func connect(_ url: URL) {
        guard url.startAccessingSecurityScopedResource() else {
            problem = "iOS didn't grant access to that folder. Try again, or use the Shortcut setup."
            return
        }
        defer { url.stopAccessingSecurityScopedResource() }
        do {
            let bookmark = try url.bookmarkData(options: .minimalBookmark, includingResourceValuesForKeys: nil, relativeTo: nil)
            try FileManager.default.createDirectory(at: bookmarkFile.deletingLastPathComponent(), withIntermediateDirectories: true)
            try bookmark.write(to: bookmarkFile, options: .atomic)
            folderURL = url; folderName = url.lastPathComponent; problem = nil
        } catch {
            problem = "That folder can't be remembered. Choose iCloud Drive › Genesis again."
            return
        }
        refresh()
    }

    private func resolveFolder() {
        guard let data = try? Data(contentsOf: bookmarkFile) else { return }
        var stale = false
        guard let url = try? URL(resolvingBookmarkData: data, bookmarkDataIsStale: &stale), !stale else {
            // Permission changed or the folder moved: ask again (Apple: handle stale bookmarks).
            try? FileManager.default.removeItem(at: bookmarkFile)
            problem = "Genesis lost access to its folder. Choose iCloud Drive › Genesis again."
            return
        }
        folderURL = url; folderName = url.lastPathComponent
    }

    /// Drops a folder whose access was revoked in Settings › Privacy › Files and Folders.
    private func lostAccess() {
        try? FileManager.default.removeItem(at: bookmarkFile)
        folderURL = nil; folderName = nil
        problem = "Genesis lost access to its folder. Choose iCloud Drive › Genesis again."
    }

    private func inFolder<T>(_ body: (URL) throws -> T) rethrows -> T? {
        guard let url = folderURL else { return nil }
        guard url.startAccessingSecurityScopedResource() else { lostAccess(); return nil }
        defer { url.stopAccessingSecurityScopedResource() }
        return try body(url)
    }

    // MARK: Sync with the Mac

    func refresh() {
        inFolder { folder in
            let file = folder.appendingPathComponent("courses.json")
            try? FileManager.default.startDownloadingUbiquitousItem(at: file)
            var error: NSError?
            NSFileCoordinator().coordinate(readingItemAt: file, options: [], error: &error) { url in
                if let data = try? Data(contentsOf: url), let decoded = try? JSONDecoder().decode(CourseFile.self, from: data), Set(decoded.courses.map(\.id)).count == decoded.courses.count {
                    courses = decoded.courses
                    if let encoded = try? JSONEncoder().encode(decoded.courses) { UserDefaults.standard.set(encoded, forKey: "courses") }
                }
            }
        }
        flush()
    }

    /// Saves locally first, then moves to iCloud Drive.
    @discardableResult
    func send(_ text: String, course: Course, session: String? = nil, seq: Int? = nil) -> Bool {
        write(Note(id: UUID().uuidString.lowercased(), course: course.id, text: text,
                   created_at: ISO8601DateFormatter().string(from: Date()), session_id: session, seq: seq))
    }

    /// Marks a burst of messages as finished so the Mac combines them right away.
    @discardableResult
    func endSession(_ session: String, course: Course, count: Int) -> Bool {
        write(Note(id: UUID().uuidString.lowercased(), course: course.id, text: "",
                   created_at: ISO8601DateFormatter().string(from: Date()), session_id: session, session_end: true, count: count))
    }

    private func write(_ note: Note) -> Bool {
        do {
            try delivery.save(note, id: note.id)
            problem = nil
            flush()
            return true
        } catch {
            problem = "This message could not be saved. Your text is still here. Check available storage and try again."
            return false
        }
    }

    // Shortcuts reports completion through a unique, persisted callback for this batch.
    func shortcutURL() -> URL? {
        do { return try delivery.shortcutURL(name: Self.shortcutName) }
        catch { problem = "Some waiting notes could not be prepared. They are still saved on this phone."; return nil }
    }

    func handle(_ url: URL) {
        do {
            guard let outcome = try delivery.handle(url) else { return }
            if outcome == "sent" {
                shortcutReady = true; problem = nil
                UserDefaults.standard.set(true, forKey: "shortcutReady")
            } else if outcome == "error" {
                problem = "The Genesis Note shortcut failed. Your notes are still saved on this phone."
            }
        } catch { problem = "Delivery confirmation could not be saved. Your notes are retained for retry." }
        refreshWaiting()
    }

    func refreshWaiting() {
        waiting = (try? FileManager.default.contentsOfDirectory(at: outbox, includingPropertiesForKeys: nil))?.filter { $0.pathExtension == "json" }.count ?? 0
    }

    private func flush() {
        guard folderURL != nil else { refreshWaiting(); return }   // no folder: the shortcut delivers
        let files = (try? FileManager.default.contentsOfDirectory(at: outbox, includingPropertiesForKeys: nil))?.filter { $0.pathExtension == "json" } ?? []
        inFolder { folder in
            let notes = folder.appendingPathComponent("Notes", isDirectory: true)
            try? FileManager.default.createDirectory(at: notes, withIntermediateDirectories: true)
            for local in files {
                guard let data = try? Data(contentsOf: local) else { continue }
                var error: NSError?
                var wrote = false
                NSFileCoordinator().coordinate(writingItemAt: notes.appendingPathComponent(local.lastPathComponent), options: .forReplacing, error: &error) { url in
                    wrote = (try? data.write(to: url, options: .atomic)) != nil
                }
                if wrote, error == nil {
                    do { try FileManager.default.removeItem(at: local) }
                    catch { problem = "A delivered note is retained for retry." }
                }
            }
        }
        refreshWaiting()
    }
}
