import SwiftUI
import UniformTypeIdentifiers

/// Picker diagnostics, built into Genesis so it runs with exactly the same signing.
/// Every step is logged on screen: which picker configuration ran, whether iOS called back,
/// whether security-scoped access was granted, whether a minimal bookmark could be made,
/// and whether a coordinated test write succeeded. It also shows what the installed
/// provisioning profile grants, so signing can be confirmed or ruled out with evidence.
@MainActor @Observable
final class DiagLog {
    var lines: [String] = []
    func add(_ s: String) {
        let t = Date().formatted(.dateTime.hour(.twoDigits(amPM: .omitted)).minute().second())
        lines.append("\(t)  \(s)")
    }
}

struct DiagnosticsView: View {
    @State private var log = DiagLog()
    @State private var swiftUIImporter = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Picker diagnostics").font(Fonts.title(30)).foregroundStyle(Palette.ink)
                Spacer()
                Button { dismiss() } label: { Image(systemName: "xmark").font(.system(size: 15, weight: .semibold)).frame(width: 30, height: 30) }
                    .glassButton().buttonBorderShape(.circle)
            }
            Text("Run each test. In each picker, go into a folder (try On My iPhone, then iCloud Drive › Genesis) and tap Open. Then copy the log and send it.")
                .font(.system(size: 13)).foregroundStyle(Palette.secondary)

            VStack(spacing: 8) {
                testButton("1  UIKit folder picker (Apple sample)") { presentUIKit(types: [.folder], asCopy: nil, label: "T1") }
                testButton("2  UIKit folder picker, asCopy: false") { presentUIKit(types: [.folder], asCopy: false, label: "T2") }
                testButton("3  SwiftUI fileImporter (folder)") { log.add("T3 presenting SwiftUI fileImporter"); swiftUIImporter = true }
                testButton("4  UIKit file picker (any file, control)") { presentUIKit(types: [.item], asCopy: nil, label: "T4") }
            }

            HStack {
                Text("LOG").font(Fonts.label(10)).tracking(1.4).foregroundStyle(Palette.tertiary)
                Spacer()
                Button("Copy log") { UIPasteboard.general.string = log.lines.joined(separator: "\n") }.font(.system(size: 13))
            }
            ScrollView {
                Text(log.lines.joined(separator: "\n"))
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(Palette.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
            }
            .padding(10)
            .background(Color.white.opacity(0.05), in: RoundedRectangle(cornerRadius: 12))
        }
        .padding(22)
        .onAppear(perform: environment)
        .fileImporter(isPresented: $swiftUIImporter, allowedContentTypes: [.folder]) { result in
            switch result {
            case .success(let url): log.add("T3 callback: success"); examine(url, label: "T3")
            case .failure(let e): log.add("T3 callback: failure \(e.localizedDescription)")
            }
        }
    }

    private func testButton(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) { Text(title).font(.system(size: 14, weight: .medium)).frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 4) }
            .glassButton()
    }

    // MARK: Environment and signing evidence

    private func environment() {
        guard log.lines.isEmpty else { return }
        let info = Bundle.main.infoDictionary ?? [:]
        log.add("bundle id: \(Bundle.main.bundleIdentifier ?? "?")")
        log.add("iOS \(UIDevice.current.systemVersion), app \(info["CFBundleShortVersionString"] ?? "?")")
        log.add(OrbStats.shared.summary)
        log.add("iCloud account token: \(FileManager.default.ubiquityIdentityToken != nil ? "present" : "absent")")
        guard let path = Bundle.main.path(forResource: "embedded", ofType: "mobileprovision"),
              let data = FileManager.default.contents(atPath: path),
              let text = String(data: data, encoding: .isoLatin1),
              let start = text.range(of: "<?xml"), let end = text.range(of: "</plist>") else {
            log.add("provisioning profile: none embedded"); return
        }
        let xml = Data(text[start.lowerBound..<end.upperBound].utf8)
        guard let plist = try? PropertyListSerialization.propertyList(from: xml, format: nil) as? [String: Any] else {
            log.add("provisioning profile: unreadable"); return
        }
        log.add("profile: \(plist["Name"] ?? "?") / team \(plist["TeamName"] ?? "?")")
        log.add("profile type: \((plist["ProvisionsAllDevices"] as? Bool) == true ? "enterprise (all devices)" : "device list")")
        if let exp = plist["ExpirationDate"] as? Date { log.add("profile expires: \(exp.formatted(date: .abbreviated, time: .omitted))") }
        if let ent = plist["Entitlements"] as? [String: Any] {
            log.add("entitlements: " + ent.keys.sorted().joined(separator: ", "))
            if let app = ent["application-identifier"] { log.add("application-identifier: \(app)") }
        }
    }

    // MARK: Picker tests

    private func presentUIKit(types: [UTType], asCopy: Bool?, label: String) {
        let picker = asCopy.map { UIDocumentPickerViewController(forOpeningContentTypes: types, asCopy: $0) }
            ?? UIDocumentPickerViewController(forOpeningContentTypes: types)
        let delegate = DiagDelegate(label: label, log: log) { url in examine(url, label: label) }
        DiagDelegate.current = delegate
        picker.delegate = delegate
        let windows = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows)
        guard let root = (windows.first(where: \.isKeyWindow) ?? windows.first)?.rootViewController else { log.add("\(label) no root view controller"); return }
        var top = root
        while let next = top.presentedViewController, !next.isBeingDismissed { top = next }
        log.add("\(label) presenting from \(type(of: top))")
        top.present(picker, animated: true) { log.add("\(label) picker on screen") }
    }

    /// What happens after iOS hands back a URL, step by step.
    private func examine(_ url: URL, label: String) {
        log.add("\(label) url: …/\(url.pathComponents.suffix(3).joined(separator: "/"))")
        let values = try? url.resourceValues(forKeys: [.isUbiquitousItemKey, .isDirectoryKey])
        log.add("\(label) iCloud item: \(values?.isUbiquitousItem.map { "\($0)" } ?? "?"), folder: \(values?.isDirectory.map { "\($0)" } ?? "?")")
        let scoped = url.startAccessingSecurityScopedResource()
        log.add("\(label) startAccessingSecurityScopedResource: \(scoped)")
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        do {
            let b = try url.bookmarkData(options: .minimalBookmark, includingResourceValuesForKeys: nil, relativeTo: nil)
            log.add("\(label) minimalBookmark: \(b.count) bytes")
        } catch { log.add("\(label) minimalBookmark failed: \(error.localizedDescription)") }
        guard values?.isDirectory == true else { return }
        let test = url.appendingPathComponent("genesis-diagnostic.txt")
        var coordError: NSError?
        var writeError: String?
        NSFileCoordinator().coordinate(writingItemAt: test, options: .forReplacing, error: &coordError) { u in
            do { try Data("Genesis diagnostic \(Date())\n".utf8).write(to: u, options: .atomic) } catch { writeError = error.localizedDescription }
        }
        if let coordError { log.add("\(label) coordinated write: coordinator error \(coordError.localizedDescription)") }
        else if let writeError { log.add("\(label) coordinated write failed: \(writeError)") }
        else { log.add("\(label) coordinated write: OK (genesis-diagnostic.txt)") }
        let listing = (try? FileManager.default.contentsOfDirectory(atPath: url.path))?.prefix(6).joined(separator: ", ") ?? "unreadable"
        log.add("\(label) folder contents: \(listing)")
    }
}

final class DiagDelegate: NSObject, UIDocumentPickerDelegate {
    static var current: DiagDelegate?
    let label: String
    let log: DiagLog
    let onPick: (URL) -> Void
    init(label: String, log: DiagLog, onPick: @escaping (URL) -> Void) { self.label = label; self.log = log; self.onPick = onPick }
    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        MainActor.assumeIsolated {
            log.add("\(label) didPickDocumentsAt: \(urls.count) url(s)")
            if let url = urls.first { onPick(url) }
        }
    }
    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
        MainActor.assumeIsolated { log.add("\(label) documentPickerWasCancelled") }
    }
}
