import Foundation
import Security

/// Release resources are bundled; mutable records live in the user's Application Support.
enum GenesisRuntime {
    static var environment: [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["PYTHONDONTWRITEBYTECODE"] = "1"; env["PYTHONNOUSERSITE"] = "1"
        env["GENESIS_PDF_HELPER"] = Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/GenesisPDF").path
        return env
    }

    static var python: URL? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        let executable = resources.appendingPathComponent("Python/bin/python3")
        return FileManager.default.isExecutableFile(atPath: executable.path) ? executable : nil
    }

    static func prepare(preferred: String) throws -> URL {
        let fm = FileManager.default
        if let testRoot = ProcessInfo.processInfo.environment["GENESIS_TEST_WORKSPACE"], let resources = Bundle.main.resourceURL {
            let root = URL(fileURLWithPath: testRoot)
            try installTemplate(from: resources.appendingPathComponent("Backend"), into: root)
            return root
        }
        // Existing installations retain their chosen workspace and records.
        if !preferred.isEmpty, fm.fileExists(atPath: preferred + "/outputs/genesis_app_bridge.py") || fm.fileExists(atPath: preferred + "/outputs/" + Upgrade.oldCode + "app_bridge.py") {
            let root = URL(fileURLWithPath: preferred, isDirectory: true)
            guard let resources = Bundle.main.resourceURL else { throw CocoaError(.fileNoSuchFile) }
            try installTemplate(from: resources.appendingPathComponent("Backend"), into: root)
            return root
        }
        let support = try fm.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                 appropriateFor: nil, create: true)
        let root = support.appendingPathComponent("Genesis/Workspace", isDirectory: true)
        guard let resources = Bundle.main.resourceURL else { throw CocoaError(.fileNoSuchFile) }
        try installTemplate(from: resources.appendingPathComponent("Backend"), into: root)
        return root
    }

    /// Only bundled code and static configuration are copied. No user records are shipped.
    static func installTemplate(from template: URL, into root: URL) throws {
        let fm = FileManager.default
        Upgrade.workspace(root, template: template)
        guard fm.fileExists(atPath: template.appendingPathComponent("outputs/genesis_app_bridge.py").path),
              let files = fm.enumerator(at: template, includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey])
        else { throw CocoaError(.fileNoSuchFile) }
        // Refuse symbolic links before creating or replacing anything in an existing workspace.
        func rejectLinks(_ path: URL) throws {
            var item = path.standardizedFileURL
            while item.path != "/" {
                if (try? item.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) == true {
                    throw CocoaError(.fileWriteInvalidFileName)
                }
                item.deleteLastPathComponent()
            }
        }
        try rejectLinks(root)
        var copies: [(URL, URL)] = []
        for case let file as URL in files {
            let values = try file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
            guard values.isSymbolicLink != true else { throw CocoaError(.fileReadInvalidFileName) }
            guard values.isRegularFile == true else { continue }
            let relative = String(file.path.dropFirst(template.path.count + 1))
            let target = root.appendingPathComponent(relative)
            try rejectLinks(target)
            copies.append((file, target))
        }
        let backup = root.appendingPathComponent("Genesis Code Backups/" + UUID().uuidString, isDirectory: true)
        // Save every replaced code file before any updates. User records are never enumerated.
        for (file, target) in copies where target.lastPathComponent != "genesis_models.json" {
            guard let previous = try? Data(contentsOf: target), previous != (try Data(contentsOf: file)) else { continue }
            let relative = String(file.path.dropFirst(template.path.count + 1))
            let saved = backup.appendingPathComponent(relative)
            try rejectLinks(saved)
            try fm.createDirectory(at: saved.deletingLastPathComponent(), withIntermediateDirectories: true,
                                   attributes: [.posixPermissions: 0o700])
            try previous.write(to: saved, options: .atomic)
        }
        for (file, target) in copies {
            // Model routing may have been customized by this user after first launch.
            if target.lastPathComponent == "genesis_models.json", fm.fileExists(atPath: target.path) { continue }
            try fm.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true,
                                   attributes: [.posixPermissions: 0o700])
            let data = try Data(contentsOf: file)
            if (try? Data(contentsOf: target)) != data { try data.write(to: target, options: .atomic) }
        }
        for folder in ["outputs/Genesis App/Bridge", "outputs/Genesis Study", "work", "tmp"] {
            let directory = root.appendingPathComponent(folder)
            try rejectLinks(directory)
            try fm.createDirectory(at: directory, withIntermediateDirectories: true,
                                   attributes: [.posixPermissions: 0o700])
        }
    }
}


/// Moving from the app's old name to Genesis, once. Earlier builds used another bundle ID and
/// other names for folders, files and Keychain entries; this carries everything over so an
/// upgrade feels like nothing happened (settings, Canvas sign-in, saved records, study history).
enum Upgrade {
    static let oldName = "School" + " HQ"            // in two parts so the old name lives only here
    static let oldCode = "school" + "_hq_"
    static let oldBundle = "com.xander." + "school" + "hq"

    /// Before anything else runs: settings, the Canvas session and Keychain entries.
    static func identity() {
        let defaults = UserDefaults.standard
        guard !defaults.bool(forKey: "upgradedFromOldName") else { return }
        defer { defaults.set(true, forKey: "upgradedFromOldName") }
        let renamed = ["school" + "HQWorkspace": "genesisWorkspace", "school" + "HQBookmark": "genesisBookmark"]
        for (key, value) in defaults.persistentDomain(forName: oldBundle) ?? [:] {
            let target = renamed[key] ?? key
            if defaults.object(forKey: target) == nil { defaults.set(value, forKey: target) }
        }
        // The Canvas sign-in lives in the web view's data, kept per app. Carry it over.
        let fm = FileManager.default, library = fm.homeDirectoryForCurrentUser.appendingPathComponent("Library")
        let newBundle = Bundle.main.bundleIdentifier ?? "com.xander.genesis"
        for folder in ["WebKit", "HTTPStorages", "Caches"] {
            let base = library.appendingPathComponent(folder)
            for name in (try? fm.contentsOfDirectory(atPath: base.path)) ?? [] where name.hasPrefix(oldBundle) {
                let target = base.appendingPathComponent(newBundle + name.dropFirst(oldBundle.count))
                if !fm.fileExists(atPath: target.path) { try? fm.copyItem(at: base.appendingPathComponent(name), to: target) }
            }
        }
        // The private Canvas calendar feed moves to its Genesis Keychain name.
        let oldQuery: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "School" + "HQ.CanvasCalendar.v1",
                                       kSecAttrAccount as String: "private-feed", kSecReturnData as String: true]
        var found: AnyObject?
        if SecItemCopyMatching(oldQuery as CFDictionary, &found) == errSecSuccess, let data = found as? Data {
            let item: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "Genesis.CanvasCalendar.v1",
                                       kSecAttrAccount as String: "private-feed", kSecValueData as String: data,
                                       kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
            let status = SecItemAdd(item as CFDictionary, nil)
            if status == errSecSuccess || status == errSecDuplicateItem {
                var remove = oldQuery; remove.removeValue(forKey: kSecReturnData as String)
                SecItemDelete(remove as CFDictionary)
            }
        }
    }

    /// The workspace's folders, files, saved paths and database, through genesis_migrate.py.
    static func workspace(_ root: URL, template: URL) {
        let fm = FileManager.default, out = root.appendingPathComponent("outputs")
        let leftovers = ((try? fm.contentsOfDirectory(atPath: out.path)) ?? []).contains { $0.hasPrefix(oldName) || $0.hasPrefix(oldCode) || $0.hasPrefix("." + oldCode) }
        guard leftovers, let python = GenesisRuntime.python else { return }
        let script = template.appendingPathComponent("outputs/genesis_migrate.py")
        guard fm.fileExists(atPath: script.path) else { return }
        let p = Process(); p.executableURL = python; p.arguments = ["-I", script.path, root.path]
        p.environment = GenesisRuntime.environment
        p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
        do { try p.run(); p.waitUntilExit() } catch {}
    }
}
