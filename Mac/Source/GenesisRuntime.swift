import Foundation

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
        if !preferred.isEmpty, fm.fileExists(atPath: preferred + "/outputs/school_hq_app_bridge.py") {
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
        guard fm.fileExists(atPath: template.appendingPathComponent("outputs/school_hq_app_bridge.py").path),
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
        for (file, target) in copies where target.lastPathComponent != "school_hq_models.json" {
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
            if target.lastPathComponent == "school_hq_models.json", fm.fileExists(atPath: target.path) { continue }
            try fm.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true,
                                   attributes: [.posixPermissions: 0o700])
            let data = try Data(contentsOf: file)
            if (try? Data(contentsOf: target)) != data { try data.write(to: target, options: .atomic) }
        }
        for folder in ["outputs/School HQ App/Bridge", "outputs/School HQ Study", "work", "tmp"] {
            let directory = root.appendingPathComponent(folder)
            try rejectLinks(directory)
            try fm.createDirectory(at: directory, withIntermediateDirectories: true,
                                   attributes: [.posixPermissions: 0o700])
        }
    }
}
