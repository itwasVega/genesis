import SwiftUI
import AppKit
import Security
import UniformTypeIdentifiers

struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @State private var mailProvider = MailProvider.icloud
    @State private var mailAddress = ""
    @State private var mailPassword = ""
    @State private var mailHost = ""
    @State private var mailPort = "993"
    @State private var mailMessage = ""
    @State private var mailBusy = false
    @State private var mailConnected: String? = nil
    @State private var feed = ""
    @State private var feedMessage = ""
    @State private var cleanup = ""
    @State private var cleanupBusy = false
    @State private var models: [ModelJob] = []
    @State private var connections = GenesisConfiguration()
    @State private var classCode = ""
    @State private var className = ""
    @State private var canvasID = ""
    @State private var setupMessage = ""
    @State private var aiMessage = ""
    @State private var testingAI = false

    var body: some View {
        TabView {
            ScrollView { VStack(alignment: .leading, spacing: 14) {
                Text("Where Genesis gathers what it needs for your brief: assignments, documents, dates and announcements. Add only what you use; anything you don't add never runs or collects anything.").font(Typeface.sans(12)).foregroundStyle(Theme.secondary)
                PluginList()
            }.padding(20) }
                .tabItem { Label("Plugins", systemImage: "puzzlepiece.extension") }
            accounts.tabItem { Label("Accounts", systemImage: "person.crop.circle") }
            studyModels.tabItem { Label("Models", systemImage: "cpu") }
            general.tabItem { Label("General", systemImage: "gearshape") }
        }
        .frame(width: 620, height: 560)
        .sheet(item: $model.setupPlugin) { item in
            WelcomeView(flow: SetupFlow(model: model, only: item.id) { model.setupPlugin = nil; model.loadPlugins(); loadConnections() })
                .environmentObject(model).frame(width: 760, height: 640)
        }
        .onAppear { loadModels(); loadMail(); loadConnections() }
    }

    // MARK: Accounts

    var accounts: some View {
        Form {
            if model.plugins.contains("canvas") {
            Section("Canvas") {
                LabeledContent("School", value: connections.canvas_host.isEmpty ? "not set" : connections.canvas_host)
                LabeledContent("Connected with", value: connections.canvas_auth == "token" ? "an access token" : "your school login page")
                ForEach(connections.courses) { course in
                    LabeledContent(course.label, value: course.id)
                }
                HStack {
                    Button("Find my classes again") { model.setupPlugin = PluginSetupID(id: "canvas") }
                    Button("Change school or sign-in") { model.setupPlugin = PluginSetupID(id: "canvas") }
                }
                if !setupMessage.isEmpty { Text(setupMessage).font(.caption) }
            }
            }
            if model.plugins.contains("email") {
            Section("Email") {
                Text("Emails from Canvas and your school, searchable in Library. Read-only: nothing is marked read, sent or deleted.")
                    .font(Typeface.sans(12)).foregroundStyle(Theme.secondary)
                if let address = mailConnected {
                    LabeledContent("Connected", value: address)
                    HStack {
                        Button(mailBusy ? "Testing…" : "Test connection") { testMail() }.disabled(mailBusy)
                        Button("Disconnect") { disconnectMail() }
                    }
                } else {
                    Picker("Provider", selection: $mailProvider) {
                        ForEach(MailProvider.allCases) { Text($0.label).tag($0) }
                    }
                    TextField("Email address", text: $mailAddress).textContentType(.emailAddress)
                    SecureField("App password", text: $mailPassword)
                    if mailProvider == .other {
                        TextField("IMAP server", text: $mailHost)
                        TextField("Port", text: $mailPort)
                    }
                    Text(mailProvider.help).font(Typeface.sans(11)).foregroundStyle(Theme.tertiary)
                    Button(mailBusy ? "Connecting…" : "Connect") { connectMail() }
                        .disabled(mailBusy || mailAddress.isEmpty || mailPassword.isEmpty || (mailProvider == .other && mailHost.isEmpty))
                }
                if !mailMessage.isEmpty { Text(mailMessage).font(Typeface.sans(12)) }
            }
            }
            Section("iPhone") {
                Text("The Genesis iPhone app drops notes into iCloud Drive › Genesis. They show up under Tell Genesis within a minute and count at your next sync.")
                    .font(Typeface.sans(12)).foregroundStyle(Theme.secondary)
                Text(phoneStatus).font(Typeface.sans(12))
                HStack {
                    Button("Choose iCloud Drive folder…") { choosePhoneFolder() }
                    if !model.phoneSeen { Button("Get the iPhone app") { model.openIPhoneApp() } }
                }
            }
            Section("What Genesis knows about you") {
                CompanionMemoryList()
            }
            CompanionSettings()
            Section("Semester") {
                Text("When your classes are over, Genesis says goodbye for now: a black window with the orb, waiting until you need it again.").font(.caption).foregroundStyle(.secondary)
                Button("Say goodbye for now") { model.setFarewell(true) }
            }
            if model.plugins.contains("calendar") {
            Section("Canvas calendar") {
                Text("Picked up from your Canvas automatically. If it ever stops, grab it again here.").font(Typeface.sans(12)).foregroundStyle(Theme.secondary)
                Button("Pick it up again") { model.setupPlugin = PluginSetupID(id: "calendar") }
                SecureField("or paste your Canvas calendar's .ics link", text: $feed)
                Button("Save to Keychain") { saveFeed() }.disabled(feed.isEmpty)
                if !feedMessage.isEmpty { Text(feedMessage).font(Typeface.sans(12)) }
            }
            }
        }
        .formStyle(.grouped)
    }

    // MARK: iPhone inbox

    var phoneStatus: String {
        let url = model.bridge.appendingPathComponent("phone-inbox.json")
        guard let data = try? Data(contentsOf: url), let v = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return "Not checked yet." }
        switch v["status"] as? String {
        case "ok": return "Ready: " + ((v["folder"] as? String).map { ($0 as NSString).abbreviatingWithTildeInPath } ?? "iCloud Drive › Genesis")
        case "icloud_drive_off": return "iCloud Drive wasn't found. Turn it on, or choose its folder below."
        case "permission_needed": return (v["detail"] as? String) ?? "macOS blocked access to iCloud Drive."
        default: return (v["detail"] as? String) ?? "Couldn't reach iCloud Drive."
        }
    }

    func choosePhoneFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.canCreateDirectories = false
        panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/CloudStorage")
        panel.prompt = "Use this folder"
        panel.message = "Choose your iCloud Drive folder (Genesis creates a Genesis folder inside it)."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let config = model.outputs.appendingPathComponent("Genesis Study/phone-inbox.json")
        try? JSONSerialization.data(withJSONObject: ["icloud_root": url.path], options: .prettyPrinted).write(to: config, options: .atomic)
        model.importPhoneNotes()
    }

    // MARK: Email (any IMAP provider)

    var mailConfigURL: URL { model.outputs.appendingPathComponent("Genesis Study/mail.json") }
    static let mailService = "Genesis.Mail.v1"

    func loadMail() {
        guard let data = try? Data(contentsOf: mailConfigURL), let v = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              v["enabled"] as? Bool == true, let address = v["email"] as? String else { mailConnected = nil; return }
        mailConnected = address
    }

    func connectMail() {
        let address = mailAddress.trimmingCharacters(in: .whitespacesAndNewlines)
        let host = mailProvider == .other ? mailHost.trimmingCharacters(in: .whitespacesAndNewlines) : mailProvider.host
        let port = mailProvider == .other ? (Int(mailPort) ?? 993) : 993
        guard address.contains("@"), !host.isEmpty else { mailMessage = "Enter a full email address."; return }
        guard storeMailPassword(account: address, password: mailPassword) else { mailMessage = "Keychain refused the password."; return }
        let config: [String: Any] = ["enabled": true, "provider": mailProvider.rawValue, "email": address, "host": host, "port": port]
        try? FileManager.default.createDirectory(at: mailConfigURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? JSONSerialization.data(withJSONObject: config, options: .prettyPrinted).write(to: mailConfigURL, options: .atomic)
        mailPassword = ""
        mailBusy = true; mailMessage = "Checking the connection…"
        model.runScript("genesis_mail.py", ["test"]) { data in
            mailBusy = false
            let v = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            if v?["ok"] as? Bool == true { mailConnected = address; mailMessage = (v?["detail"] as? String) ?? "Connected." }
            else {
                mailMessage = (v?["detail"] as? String) ?? "The connection test could not run."
                removeMailConfig(address: address)
            }
        }
    }

    func testMail() {
        mailBusy = true; mailMessage = ""
        model.runScript("genesis_mail.py", ["test"]) { data in
            mailBusy = false
            let v = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            mailMessage = (v?["detail"] as? String) ?? "The connection test could not run."
        }
    }

    func disconnectMail() {
        if let address = mailConnected { removeMailConfig(address: address) }
        mailConnected = nil; mailMessage = "Disconnected. Saved messages stay searchable."
    }

    func removeMailConfig(address: String) {
        SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: Self.mailService, kSecAttrAccount as String: address] as CFDictionary)
        try? FileManager.default.removeItem(at: mailConfigURL)
    }

    /// Stores the app password so the sync worker can read it with /usr/bin/security without a
    /// Keychain prompt on every sync: the item trusts this app and the security tool only.
    func storeMailPassword(account: String, password: String) -> Bool {
        let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: Self.mailService, kSecAttrAccount as String: account]
        SecItemDelete(base as CFDictionary)
        var item = base
        item[kSecValueData as String] = Data(password.utf8)
        item[kSecAttrLabel as String] = "Genesis email (read-only IMAP)"
        var me: SecTrustedApplication?, tool: SecTrustedApplication?, access: SecAccess?
        if SecTrustedApplicationCreateFromPath(nil, &me) == errSecSuccess,
           SecTrustedApplicationCreateFromPath("/usr/bin/security", &tool) == errSecSuccess,
           let me, let tool,
           SecAccessCreate("Genesis email" as CFString, [me, tool] as CFArray, &access) == errSecSuccess, let access {
            item[kSecAttrAccess as String] = access
        }
        return SecItemAdd(item as CFDictionary, nil) == errSecSuccess
    }


    func saveFeed() {
        guard let url = URL(string: feed), url.scheme == "https", url.host == connections.canvas_host, url.path.hasSuffix(".ics") else { feedMessage = "Paste the private .ics link from your Canvas calendar."; return }
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "Genesis.CanvasCalendar.v1", kSecAttrAccount as String: "private-feed"]
        let data = Data(feed.utf8)
        var status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var item = query; item[kSecValueData as String] = data; item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            status = SecItemAdd(item as CFDictionary, nil)
        }
        guard status == errSecSuccess else { feedMessage = "Keychain refused the link (\(status))."; return }
        let config = model.bridge.appendingPathComponent("optional-sources-config.json")
        var value = ((try? Data(contentsOf: config)).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }) ?? [:]
        value["calendar_enabled"] = true
        try? JSONSerialization.data(withJSONObject: value).write(to: config, options: .atomic)
        feed = ""; feedMessage = "Saved. Used on your next sync."
    }

    // MARK: Models

    func loadConnections() {
        do { connections = try GenesisConfiguration.load(root: model.workspace) }
        catch { setupMessage = error.localizedDescription }
    }

    @discardableResult
    func saveConnections(_ value: GenesisConfiguration) -> Bool {
        do {
            try value.save(root: model.workspace)
            connections = value; setupMessage = "Saved. Your class list updates on the iPhone when its folder syncs."
            model.importPhoneNotes()
            return true
        } catch { setupMessage = error.localizedDescription; return false }
    }

    func chooseCodex() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false; panel.canChooseFiles = true
        panel.message = "Choose the Codex executable installed from OpenAI."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        guard FileManager.default.isExecutableFile(atPath: url.path) else { aiMessage = "Choose an executable Codex file."; return }
        var updated = connections; updated.codex_path = url.path
        if saveConnections(updated) { aiMessage = "Selected. Test the connection after signing in to Codex." }
    }

    func testAI() {
        testingAI = true; aiMessage = "Checking sign-in and available models…"
        model.runScript("genesis_ai_setup.py", ["check"]) { data in
            testingAI = false
            guard let data, let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                aiMessage = "The connection check could not run. Reopen Genesis and try again."; return
            }
            aiMessage = result["detail"] as? String ?? "Check complete."
            if result["ok"] as? Bool == true { loadModels() }
        }
    }

    struct ModelJob: Identifiable { var id: String; var model: String; var effort: String; var why: String }
    @State private var modelChoices = ["auto"]
    @State private var modelMode = "auto"
    let effortChoices = ["low", "medium", "high", "xhigh", "max"]
    let jobTitles = ["catalog": "Read practice files", "context": "Label your notes", "facts": "Exam updates", "generate": "Write problems", "verify": "Check problems", "grade": "Grade answers", "companion": "Help when you're stuck", "scout": "Find past exams"]

    var configURL: URL { model.outputs.appendingPathComponent("genesis_models.json") }

    var studyModels: some View {
        Form {
            Section("Connect AI") {
                Text("This beta uses your own Codex installation and account. Install Codex from OpenAI, sign in, then choose its executable here. AI work uses your account's limits and sends the relevant course material to OpenAI.").font(.caption)
                Link("Open Codex setup", destination: URL(string: "https://github.com/openai/codex#installing-and-running-codex")!)
                Text(connections.codex_path.isEmpty ? "No Codex executable selected" : (connections.codex_path as NSString).abbreviatingWithTildeInPath).font(.caption)
                HStack {
                    Button("Choose Codex…") { chooseCodex() }
                    Button(testingAI ? "Checking…" : "Test connection") { testAI() }.disabled(testingAI)
                }
                if !aiMessage.isEmpty { Text(aiMessage).font(.caption) }
            }
            Section {
                Picker("Models", selection: $modelMode) { Text("Auto").tag("auto"); Text("Manual").tag("manual") }
                    .pickerStyle(.segmented)
                    .onChange(of: modelMode) { _, value in saveMode(value) }
                Text(modelMode == "auto"
                     ? "Genesis picks the model and strength for every job from what your account offers, and checks every problem with a different model when it can."
                     : "Choose the model and strength for each job.")
                    .font(Typeface.sans(12)).foregroundStyle(Theme.secondary)
            }
            if modelMode == "manual" {
                ForEach($models) { $job in
                    Section(jobTitles[job.id] ?? job.id) {
                        Picker("Model", selection: $job.model) { ForEach(modelChoices, id: \.self) { Text($0) } }
                        Picker("Strength", selection: $job.effort) { ForEach(effortChoices, id: \.self) { Text($0) } }
                        Text(job.why).font(Typeface.sans(11)).foregroundStyle(Theme.tertiary)
                    }
                }
                Section { Button("Save model choices") { saveModels() } }
            }
        }
        .formStyle(.grouped)
    }

    func loadModels() {
        let available = model.outputs.appendingPathComponent("Genesis Study/ai-available.json")
        if let data = try? Data(contentsOf: available), let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let names = value["models"] as? [String] { modelChoices = names }
        guard let data = try? Data(contentsOf: configURL), let v = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let jobs = v["jobs"] as? [String: [String: String]] else { return }
        modelMode = (v["mode"] as? String) == "manual" ? "manual" : "auto"
        let order = ["generate", "verify", "grade", "scout", "catalog", "facts", "context", "companion"]
        models = order.compactMap { k in jobs[k].map { ModelJob(id: k, model: $0["model"] ?? "gpt-6.1-sol", effort: $0["effort"] ?? "medium", why: $0["why"] ?? "") } }
        modelChoices = Array(Set(modelChoices + models.map(\.model))).sorted()
    }

    func saveMode(_ value: String) {
        guard let data = try? Data(contentsOf: configURL), var v = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        v["mode"] = value
        if let out = try? JSONSerialization.data(withJSONObject: v, options: [.prettyPrinted, .sortedKeys]) { try? out.write(to: configURL, options: .atomic) }
    }

    func saveModels() {
        guard let data = try? Data(contentsOf: configURL), var v = try? JSONSerialization.jsonObject(with: data) as? [String: Any], var jobs = v["jobs"] as? [String: [String: String]] else { return }
        for m in models { var j = jobs[m.id] ?? [:]; j["model"] = m.model; j["effort"] = m.effort; jobs[m.id] = j }
        v["jobs"] = jobs
        if let out = try? JSONSerialization.data(withJSONObject: v, options: [.prettyPrinted, .sortedKeys]) { try? out.write(to: configURL, options: .atomic) }
    }

    // MARK: General

    var general: some View {
        Form {
            Section {
                VStack(alignment: .leading, spacing: 6) {
                    GenesisWordmark().frame(height: 22)
                    Text("Every day starts from what's actually on your courses.").font(Typeface.sans(12)).foregroundStyle(Theme.secondary)
                }
                .padding(.vertical, 4)
            }
            Section("Welcome") {
                Button("Meet Genesis again") { model.welcoming = true }
            }
            Section("Appearance") {
                Picker("Theme", selection: Binding(get: { model.appearance }, set: { model.setAppearance($0) })) {
                    Text("System").tag("system"); Text("Light").tag("light"); Text("Dark").tag("dark")
                }
                .pickerStyle(.segmented)
            }
            Section("Folder") {
                Text(model.workspace.isEmpty ? "Not chosen" : model.workspace).font(Typeface.mono(11)).foregroundStyle(Theme.secondary).textSelection(.enabled)
                Button("Choose folder…") { model.chooseWorkspace() }
            }
            Section("Notifications") {
                Button("Allow notifications when a plan is ready") { model.enableNotifications() }
            }
            Section("Storage") {
                Text("Removes old run copies and duplicate search entries. Anything a plan cites, and every course original, is kept.")
                    .font(Typeface.sans(12)).foregroundStyle(Theme.secondary)
                HStack {
                    Button("Preview cleanup") { runCleanup(apply: false) }.disabled(cleanupBusy)
                    Button("Clean up") { runCleanup(apply: true) }.disabled(cleanupBusy || cleanup.isEmpty)
                    if cleanupBusy { ProgressView().controlSize(.small) }
                }
                if !cleanup.isEmpty { Text(cleanup).font(Typeface.mono(11)).foregroundStyle(Theme.secondary) }
            }
        }
        .formStyle(.grouped)
    }

    func runCleanup(apply: Bool) {
        cleanupBusy = true
        model.runScript("genesis_retention.py", apply ? ["--apply"] : []) { data in
            cleanupBusy = false
            guard let data, let v = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { cleanup = "Cleanup could not run."; return }
            let files = v["files"] as? Int ?? 0, mb = v["mb"] as? Double ?? 0
            let db = v["database"] as? [String: Any] ?? [:]
            if apply {
                cleanup = "Removed \(files) files (\(mb) MB). Database \(db["db_mb_before"] ?? "?") → \(db["db_mb_after"] ?? "?") MB."
            } else {
                cleanup = "\(files) files (\(mb) MB) can go. Search index: \(db["fts_rows"] ?? "?") rows for \(db["unique_documents"] ?? "?") unique documents (\(db["db_mb"] ?? "?") MB)."
            }
        }
    }
}

enum MailProvider: String, CaseIterable, Identifiable {
    case icloud, gmail, outlook, yahoo, other
    var id: String { rawValue }
    var label: String { ["icloud": "iCloud", "gmail": "Gmail", "outlook": "Outlook / Hotmail", "yahoo": "Yahoo", "other": "Other (IMAP)"][rawValue]! }
    var host: String { ["icloud": "imap.mail.me.com", "gmail": "imap.gmail.com", "outlook": "outlook.office365.com", "yahoo": "imap.mail.yahoo.com", "other": ""][rawValue]! }
    var help: String {
        switch self {
        case .icloud: return "Create an app-specific password at account.apple.com → Sign-In and Security."
        case .gmail: return "Needs 2-Step Verification, then an app password at myaccount.google.com/apppasswords. No weekly reconnects."
        case .outlook: return "Microsoft is retiring password sign-in for Outlook mail apps; this may be refused. iCloud or Gmail are more reliable."
        case .yahoo: return "Generate an app password in Yahoo Account Security."
        case .other: return "Any provider with IMAP over SSL. Use an app password if your provider offers one."
        }
    }
}


/// Everything the orb has picked up about you in its break chats, saved only on this Mac.
/// Delete any line, or all of it.
struct CompanionMemoryList: View {
    @EnvironmentObject var model: AppModel
    struct Fact: Identifiable, Hashable { var id: String; var text: String }
    @State private var facts: [Fact] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Things you've told the orb during breaks. It uses them to know you, nothing else, and they stay on this Mac.").font(.caption).foregroundStyle(.secondary)
            if facts.isEmpty {
                Text("Nothing yet.").foregroundStyle(.secondary)
            } else {
                ForEach(facts) { f in
                    HStack {
                        Text(f.text)
                        Spacer()
                        Button("Forget") { run(["forget", "--id", f.id]) }.buttonStyle(.borderless)
                    }
                }
                Button("Forget everything") { run(["forget", "--id", "all"]) }
            }
        }
        .onAppear { run(["memory"]) }
    }

    private func run(_ args: [String]) {
        model.runScript("genesis_companion.py", args) { data in
            guard let data, let v = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let list = v["facts"] as? [[String: Any]] else { return }
            facts = list.compactMap { f in (f["id"] as? String).map { Fact(id: $0, text: f["text"] as? String ?? "") } }
        }
    }
}


/// The companion is always part of Genesis. You can give it a rest here: for a while, or
/// until you turn it back on.
struct CompanionSettings: View {
    @ObservedObject private var companion = Companion.shared
    @State private var quiet = UserDefaults.standard.bool(forKey: "companionQuiet")

    var body: some View {
        Section("Genesis companion") {
            if companion.paused, let until = companion.pausedUntil {
                HStack {
                    Image(systemName: "moon.zzz").foregroundStyle(Theme.secondary)
                    Text(until > Date().addingTimeInterval(3600 * 24 * 365) ? "Off until you turn it back on"
                         : "Off until " + until.formatted(Calendar.current.isDateInToday(until) ? .dateTime.hour().minute() : .dateTime.weekday(.wide).hour().minute()))
                        .font(Typeface.sans(13))
                    Spacer()
                    Button("Turn back on") { companion.pause(until: nil) }
                }
            } else {
                HStack {
                    Text("On. It shows up on its own when you need it, and you can always say not now.").font(Typeface.sans(12)).foregroundStyle(Theme.secondary)
                    Spacer()
                    Menu("Turn off…") {
                        Button("For 1 hour") { companion.pause(until: Date().addingTimeInterval(3600)) }
                        Button("For 4 hours") { companion.pause(until: Date().addingTimeInterval(4 * 3600)) }
                        Button("Until tomorrow") { companion.pause(until: Calendar.current.startOfDay(for: Date().addingTimeInterval(86400)).addingTimeInterval(6 * 3600)) }
                        Button("For a week") { companion.pause(until: Date().addingTimeInterval(7 * 86400)) }
                        Divider()
                        Button("Until I turn it back on") { companion.pause(until: .distantFuture) }
                    }
                    .fixedSize()
                }
            }
            Toggle("A soft sound when Genesis arrives", isOn: $quiet.inverted)
                .onChange(of: quiet) { _, v in UserDefaults.standard.set(v, forKey: "companionQuiet") }
        }
    }
}

private extension Binding where Value == Bool {
    var inverted: Binding<Bool> { Binding(get: { !wrappedValue }, set: { wrappedValue = !$0 }) }
}
