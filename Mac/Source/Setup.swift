import SwiftUI
import AppKit
import CoreImage.CIFilterBuiltins
import UserNotifications

// MARK: - Meeting Genesis
//
// The first time Genesis opens, the window is pure black. A small light appears, grows, and
// becomes the orb: that's Genesis, and she introduces herself. Then she walks you through
// everything she needs, one thing at a time, in plain words, with nothing to figure out:
//   your name → her brain (your ChatGPT account, found for you) → your school's Canvas
//   (a Canvas access token, drawn step by step; your school's login page if tokens are off) → your classes (found for you) → your Canvas
//   calendar (picked up for you) → school email (optional) → the iPhone app → a tap on the
//   shoulder (notifications) → your first plan.
// The same steps open on their own when you add a plugin later, so nothing ever needs a trip
// into Settings.

enum SetupStep: Int, CaseIterable { case intro, name, brain, school, connect, classes, extras, phone, notify, done }

@MainActor
final class SetupFlow: ObservableObject {
    @Published var step: SetupStep = .intro
    /// When a single plugin is being added from Settings, the flow is just that plugin's steps.
    var only: String?
    weak var model: AppModel?
    var finished: () -> Void = {}

    init(model: AppModel?, only: String? = nil, finished: @escaping () -> Void = {}) {
        self.model = model; self.only = only; self.finished = finished
        name = UserDefaults.standard.string(forKey: "userName") ?? ""
        if let c = model.flatMap({ try? GenesisConfiguration.load(root: $0.workspace) }) {
            host = c.canvas_host; schoolTyped = c.canvas_host; auth = c.canvas_auth
        }
        switch only {
        case "canvas": step = .school
        case "email": step = .extras
        case "calendar": step = .classes
        default: step = .intro
        }
    }

    // MARK: You
    @Published var name = ""
    var hi: String { name.isEmpty ? "" : ", " + name.lowercased() }

    // MARK: Her brain (your ChatGPT account, through Codex)
    enum Brain: Equatable { case idle, looking, ready, signIn, missing, problem(String) }
    @Published var brain: Brain = .idle

    static let chatGPTDownload = URL(string: "https://openai.com/chatgpt/download/")!

    /// Finds Codex on this Mac: inside the ChatGPT app, or a standalone install.
    static func findCodex() -> String? {
        let fm = FileManager.default, home = fm.homeDirectoryForCurrentUser.path
        var candidates = ["/opt/homebrew/bin/codex", "/usr/local/bin/codex", home + "/.local/bin/codex",
                          home + "/.npm-global/bin/codex", home + "/.bun/bin/codex", home + "/.volta/bin/codex"]
        for app in ["/Applications/ChatGPT.app", home + "/Applications/ChatGPT.app", "/Applications/Codex.app", home + "/Applications/Codex.app"] {
            let resources = URL(fileURLWithPath: app).appendingPathComponent("Contents")
            if let walk = fm.enumerator(at: resources, includingPropertiesForKeys: [.isExecutableKey, .isRegularFileKey], options: [.skipsHiddenFiles]) {
                for case let url as URL in walk where url.lastPathComponent == "codex" { candidates.insert(url.path, at: 0) }
            }
        }
        return candidates.first { path in
            var dir: ObjCBool = false
            return fm.fileExists(atPath: path, isDirectory: &dir) && !dir.boolValue && fm.isExecutableFile(atPath: path)
        }
    }

    func wakeUp() {
        guard let model else { return }
        brain = .looking
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.9) { [self] in
            guard let path = Self.findCodex() else { withAnimation { brain = .missing }; return }
            var c = (try? GenesisConfiguration.load(root: model.workspace)) ?? GenesisConfiguration()
            c.codex_path = path
            try? c.save(root: model.workspace)
            model.runScript("genesis_ai_setup.py", ["check"]) { [self] data in
                let v = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
                withAnimation(.easeOut(duration: 0.3)) {
                    if v["ok"] as? Bool == true { brain = .ready }
                    else {
                        let detail = (v["detail"] as? String) ?? ""
                        brain = detail.lowercased().contains("sign in") ? .signIn : .problem(detail.isEmpty ? "I couldn't reach it just now." : detail)
                    }
                }
                if brain == .ready { DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { self.next() } }
            }
        }
    }

    // MARK: Your school's Canvas
    @Published var schoolTyped = ""
    @Published var host = ""
    @Published var auth = "signin"
    /// How you chose to connect on this pass: nil until you pick.
    @Published var method: String?
    @Published var tokenTyped = ""
    /// Where you are in the access-token guide: 0 is the hello, 1–4 are the drawn steps.
    @Published var guide = 0
    enum CanvasState: Equatable { case idle, waiting, checking, problem(String) }
    @Published var canvasState: CanvasState = .idle
    @Published var courses: [LocalCanvas.FoundCourse] = []
    @Published var calendarFound = false
    private var watcher: Timer?

    var canvas: LocalCanvas? { model?.canvas }
    var problemText: String? { if case .problem(let p) = canvasState { return p }; return nil }
    var mailProblem: String? { if case .problem(let p) = mail { return p }; return nil }
    var mailConnected: String? { if case .connected(let a) = mail { return a }; return nil }

    func chooseSchool() -> Bool {
        guard let h = CanvasAddress.host(from: schoolTyped) else { canvasState = .problem("that doesn't look like a Canvas address yet. try copying it from your browser while you're on Canvas."); return false }
        host = h; UserDefaults.standard.set(h, forKey: "canvasHost"); canvasState = .idle
        return true
    }

    /// The fallback, for schools that turn access tokens off: the school's own Canvas login,
    /// inside Genesis. Genesis watches for the moment you're in, then moves on by itself.
    func startSignIn() {
        guard let canvas else { return }
        method = "signin"; auth = "signin"
        canvasState = .waiting
        canvas.openSignIn()
        watcher?.invalidate()
        watcher = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.canvasState == .waiting, let canvas = self.canvas,
                      canvas.web.url?.host == self.host, canvas.web.url?.path.contains("login") == false else { return }
                if await canvas.whoAmI() != nil { self.watcher?.invalidate(); await self.loadCourses() }
            }
        }
    }

    /// Back to the main path: an access token, with the drawn guide.
    func useTokenPath() {
        watcher?.invalidate()
        method = "token"; canvasState = .idle
        withAnimation(.easeOut(duration: 0.3)) { guide = 0 }
    }

    func useToken() async {
        let t = tokenTyped.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.count > 20 else { canvasState = .problem("that token looks too short. copy the whole thing, it's a long one."); return }
        auth = "token"
        method = "token"
        guard CanvasToken.save(t, host: host) else { canvasState = .problem("your Mac's Keychain didn't let me save it. try once more?"); return }
        canvasState = .checking
        if await canvas?.whoAmI() == nil {
            CanvasToken.remove(host: host)
            canvasState = .problem("Canvas didn't accept that token. make sure it's from " + host + " and hasn't expired.")
            return
        }
        tokenTyped = ""
        await loadCourses()
    }

    func loadCourses() async {
        guard let canvas else { return }
        canvasState = .checking
        do {
            courses = try await canvas.findCourses()
            canvasState = .idle
            withAnimation(.spring(response: 0.5, dampingFraction: 0.85)) { step = .classes }
        } catch { canvasState = .problem("I got in, but couldn't read your classes: " + error.localizedDescription) }
    }

    /// Class codes and names, the way you'd say them: "COP3502C" and "Computer Science I".
    static func shortID(_ c: LocalCanvas.FoundCourse) -> String {
        if let r = c.code.range(of: "[A-Za-z]{2,4}[ -]?[0-9]{3,4}[A-Za-z]?", options: .regularExpression) {
            return c.code[r].replacingOccurrences(of: " ", with: "").replacingOccurrences(of: "-", with: "").uppercased()
        }
        let letters = (c.code.isEmpty ? c.name : c.code).filter { $0.isLetter || $0.isNumber }
        return String(letters.prefix(16)).isEmpty ? "Class" + c.id.suffix(4) : String(letters.prefix(16))
    }
    static func friendlyName(_ c: LocalCanvas.FoundCourse) -> String {
        var n = c.name
        for junk in [c.code, shortID(c)] where !junk.isEmpty { n = n.replacingOccurrences(of: junk, with: "") }
        n = n.replacingOccurrences(of: "^[\\s\\-:–|.0-9]*([A-Za-z]{0,3}[0-9]{2,4}\\s+)?", with: "", options: .regularExpression)
        n = n.trimmingCharacters(in: .whitespacesAndNewlines.union(CharacterSet(charactersIn: "-–:|")))
        return String((n.isEmpty ? c.name : n).prefix(60))
    }

    func saveClasses() async {
        guard let model else { return }
        var c = (try? GenesisConfiguration.load(root: model.workspace)) ?? GenesisConfiguration()
        var used = Set<String>()
        var rows: [GenesisCourse] = []
        for f in courses where f.picked {
            var id = Self.shortID(f); var n = 2
            while used.contains(id) { id = Self.shortID(f) + "-\(n)"; n += 1 }
            used.insert(id)
            rows.append(GenesisCourse(id: id, label: Self.friendlyName(f), canvas_id: f.id, aliases: nil, language: nil,
                                      instructors: f.teachers.isEmpty ? nil : f.teachers, term: f.term.isEmpty ? nil : f.term))
        }
        c.courses = rows
        c.canvas_host = host; c.canvas_auth = method ?? auth
        c.plugins["canvas"] = true
        if c.timezone == nil { c.timezone = TimeZone.current.identifier }
        do { try c.save(root: model.workspace) } catch { canvasState = .problem(error.localizedDescription); return }
        model.loadPlugins()
        await grabCalendar()
        withAnimation(.spring(response: 0.5, dampingFraction: 0.85)) { if only == "canvas" { step = .done } else { next() } }
    }

    /// Every student's Canvas has a private calendar feed; Genesis picks it up so due dates that
    /// only live on the calendar never slip by. Nothing to copy or paste.
    func grabCalendar() async {
        guard let model, let canvas, let feed = await canvas.calendarFeed(), let url = URL(string: feed), url.host == host else { return }
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "Genesis.CanvasCalendar.v1", kSecAttrAccount as String: "private-feed"]
        SecItemDelete(query as CFDictionary)
        var item = query; item[kSecValueData as String] = Data(feed.utf8); item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else { return }
        let config = model.bridge.appendingPathComponent("optional-sources-config.json")
        var value = ((try? Data(contentsOf: config)).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }) ?? [:]
        value["calendar_enabled"] = true
        try? JSONSerialization.data(withJSONObject: value).write(to: config, options: .atomic)
        model.setPlugin("calendar", true)
        withAnimation { calendarFound = true }
    }

    /// Adding Calendar on its own: use the Canvas connection that's already there.
    func calendarOnly() async {
        guard let canvas, !host.isEmpty else { step = .school; only = "canvas"; return }
        canvasState = .checking
        if canvas.token == nil, canvas.web.url?.host != host {
            canvas.web.load(URLRequest(url: URL(string: canvas.origin + "/")!))
            for _ in 0..<40 { if !canvas.web.isLoading && canvas.web.url?.host == host { break }; try? await Task.sleep(nanoseconds: 200_000_000) }
        }
        await grabCalendar()
        canvasState = calendarFound ? .idle : .problem("I need to see your Canvas first. let's sign in, then I'll grab it.")
        if calendarFound { DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) { self.finished() } }
    }

    // MARK: School email
    @Published var mailAddress = ""
    @Published var mailPassword = ""
    @Published var mailProvider: MailProvider = .outlook
    enum MailState: Equatable { case idle, open, checking, connected(String), problem(String) }
    @Published var mail: MailState = .idle

    func guessProvider() {
        let d = mailAddress.split(separator: "@").last.map(String.init)?.lowercased() ?? ""
        if d.hasSuffix("gmail.com") || d.hasSuffix("googlemail.com") { mailProvider = .gmail }
        else if ["icloud.com", "me.com", "mac.com"].contains(d) { mailProvider = .icloud }
        else if d.hasSuffix("yahoo.com") { mailProvider = .yahoo }
        else { mailProvider = .outlook }   // most schools run their email on Microsoft
    }

    func connectMail() {
        guard let model else { return }
        let address = mailAddress.trimmingCharacters(in: .whitespacesAndNewlines)
        guard address.contains("@"), !mailPassword.isEmpty else { mail = .problem("I need your full school email and the app password."); return }
        mail = .checking
        guard MailKeychain.store(account: address, password: mailPassword) else { mail = .problem("your Mac's Keychain didn't let me save it."); return }
        let url = model.outputs.appendingPathComponent("Genesis Study/mail.json")
        let config: [String: Any] = ["enabled": true, "provider": mailProvider.rawValue, "email": address, "host": mailProvider.host, "port": 993]
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? JSONSerialization.data(withJSONObject: config, options: .prettyPrinted).write(to: url, options: .atomic)
        mailPassword = ""
        model.runScript("genesis_mail.py", ["test"]) { [self] data in
            let v = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            if v?["ok"] as? Bool == true {
                var c = (try? GenesisConfiguration.load(root: model.workspace)) ?? GenesisConfiguration()
                c.school_email = address; try? c.save(root: model.workspace)
                model.setPlugin("email", true)
                withAnimation { mail = .connected(address) }
            } else {
                MailKeychain.remove(account: address); try? FileManager.default.removeItem(at: url)
                withAnimation { mail = .problem((v?["detail"] as? String) ?? "that didn't connect. double-check the app password?") }
            }
        }
    }

    // MARK: Moving along
    func next() {
        let order: [SetupStep] = [.intro, .name, .brain, .school, .connect, .classes, .extras, .phone, .notify, .done]
        guard let i = order.firstIndex(of: step), i + 1 < order.count else { return }
        var n = order[i + 1]
        if n == .phone && (model?.phoneSeen ?? false) { n = .notify }
        withAnimation(.spring(response: 0.55, dampingFraction: 0.86)) { step = n }
        if n == .brain && brain == .idle { wakeUp() }
    }

    func finish() {
        guard let model else { finished(); return }
        UserDefaults.standard.set(name.trimmingCharacters(in: .whitespacesAndNewlines), forKey: "userName")
        var c = (try? GenesisConfiguration.load(root: model.workspace)) ?? GenesisConfiguration()
        c.plugins_chosen = true
        if only == nil { c.welcomed = true }
        try? c.save(root: model.workspace)
        model.loadPlugins()
        if only == nil, model.plugins.contains("canvas"), !c.courses.isEmpty { model.requestSync() }
        finished()
    }
}

/// The school email password lives in the Keychain, shared with Settings.
enum MailKeychain {
    static func store(account: String, password: String) -> Bool {
        let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: SettingsView.mailService, kSecAttrAccount as String: account]
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
    static func remove(account: String) {
        SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: SettingsView.mailService, kSecAttrAccount as String: account] as CFDictionary)
    }
}

// MARK: - The welcome window

struct WelcomeView: View {
    @EnvironmentObject var model: AppModel
    @StateObject var flow: SetupFlow
    @Environment(\.accessibilityReduceMotion) private var reduce

    // The reveal: a point of light, then the orb.
    @State private var spark = false
    @State private var bloom = false
    @State private var orb = false
    @State private var words = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            VStack(spacing: 0) {
                Spacer(minLength: 30)
                ZStack {
                    // A small light in the dark...
                    Circle().fill(.white)
                        .frame(width: 7, height: 7)
                        .blur(radius: bloom ? 18 : 1.5)
                        .scaleEffect(bloom ? 9 : 1)
                        .opacity(spark ? (bloom ? 0 : 1) : 0)
                        .shadow(color: .white.opacity(0.9), radius: spark ? 8 : 0)
                    // ...that turns out to be her.
                    OrbView(successID: flow.step == .done ? 1 : 0, configuration: OrbConfiguration(pace: 1.6, breathe: 1), floating: orb,
                            speakID: flow.step.rawValue, mood: mood)
                        .frame(width: orbSize, height: orbSize)
                        .scaleEffect(orb ? 1 : 0.04)
                        .opacity(orb ? 1 : 0)
                }
                .frame(height: flow.step == .connect ? 96 : 200)
                .animation(.spring(response: 0.7, dampingFraction: 0.8), value: orbSize)

                Group {
                    if words { stepView.id(flow.step).transition(.asymmetric(insertion: .opacity.combined(with: .offset(y: 14)), removal: .opacity)) }
                }
                .frame(maxWidth: 560)
                .padding(.horizontal, 40)
                .padding(.top, 18)
                Spacer(minLength: 30)
            }
            if flow.only != nil {
                VStack { HStack { Spacer(); Button("Close") { flow.finished() }.buttonStyle(.plain).foregroundStyle(.white.opacity(0.4)).padding(16) }; Spacer() }
            }
        }
        .environment(\.colorScheme, .dark)
        .onAppear(perform: reveal)
    }

    private var orbSize: CGFloat { [.connect, .classes].contains(flow.step) ? 88 : (flow.step == .intro ? 170 : 128) }
    private var mood: String {
        switch flow.step {
        case .intro: return words ? "happy" : "neutral"
        case .name: return flow.name.isEmpty ? "curious" : "listening"
        case .brain: return flow.brain == .ready ? "happy" : (flow.brain == .looking ? "thinking" : "empathetic")
        case .connect: return flow.canvasState == .checking ? "thinking" : "listening"
        case .classes: return "proud"
        case .done: return "happy"
        default: return "playful"
        }
    }

    private func reveal() {
        if flow.only != nil || reduce { spark = true; bloom = true; orb = true; words = true; return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { withAnimation(.easeIn(duration: 1.6)) { spark = true } }
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.4) {
            withAnimation(.easeOut(duration: 2.2)) { bloom = true }
            withAnimation(.spring(response: 2.4, dampingFraction: 0.9)) { orb = true }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 5.6) { withAnimation(.easeOut(duration: 0.8)) { words = true } }
    }

    @ViewBuilder private var stepView: some View {
        switch flow.step {
        case .intro: intro
        case .name: nameStep
        case .brain: brainStep
        case .school: schoolStep
        case .connect: connectStep
        case .classes: classesStep
        case .extras: extrasStep
        case .phone: phoneStep
        case .notify: notifyStep
        case .done: doneStep
        }
    }

    // MARK: Steps

    private var intro: some View {
        VStack(spacing: 18) {
            Said2(big: "hey.")
            Said2(text: "I'm Genesis.", delay: 0.9)
            Said2(text: "I'll be with you this semester. the deadlines, the late nights, the days it all feels like a lot. you don't have to carry it by yourself anymore.", small: true, delay: 1.8)
            Buttons(delay: 4.4) { Button("hi, Genesis") { flow.next() }.welcomePrimary() }
        }
    }

    private var nameStep: some View {
        VStack(spacing: 18) {
            Said2(big: "what should I call you?")
            GlassField(placeholder: "your name", text: $flow.name) { flow.next() }
                .frame(maxWidth: 300)
            Buttons {
                Button(flow.name.isEmpty ? "skip for now" : "that's me") { flow.next() }.welcomePrimary()
            }
        }
    }

    private var brainStep: some View {
        VStack(spacing: 16) {
            switch flow.brain {
            case .idle, .looking:
                Said2(big: "nice to meet you\(flow.hi).")
                Said2(text: "first, let me wake up all the way. I think with your ChatGPT account, so I'm looking for it on your Mac…", small: true)
            case .ready:
                Said2(big: "there it is. I'm awake.")
                Said2(text: "I'll only share what I need to make your practice and plans. your stuff stays on this Mac.", small: true)
            case .signIn:
                Said2(big: "almost.")
                Said2(text: "I found ChatGPT, but you're not signed in yet. open it, sign in, then come right back. I'll wait.", small: true)
                Buttons {
                    Button("open ChatGPT") { NSWorkspace.shared.open(URL(fileURLWithPath: "/Applications/ChatGPT.app")) }.welcomeSecondary()
                    Button("I'm signed in") { flow.wakeUp() }.welcomePrimary()
                }
            case .missing:
                Said2(big: "I need one thing first.")
                Said2(text: "I think using the ChatGPT app. it's free and takes a minute: download it, open it, sign in, then come back here.", small: true)
                Buttons {
                    Button("get ChatGPT") { NSWorkspace.shared.open(SetupFlow.chatGPTDownload) }.welcomeSecondary()
                    Button("I've got it now") { flow.wakeUp() }.welcomePrimary()
                }
            case .problem(let detail):
                Said2(big: "hm, something's off.")
                Said2(text: detail, small: true)
                Buttons { Button("try again") { flow.wakeUp() }.welcomePrimary() }
            }
            if flow.brain != .ready && flow.brain != .looking && flow.brain != .idle {
                Button("do this later") { flow.next() }.buttonStyle(.plain).font(Typeface.sans(12)).foregroundStyle(.white.opacity(0.4))
            }
        }
    }

    private var schoolStep: some View {
        VStack(spacing: 16) {
            Said2(big: "now, where do your classes live?")
            Said2(text: "paste your school's Canvas address. it's in your browser's address bar when you're on Canvas, like canvas.yourschool.edu. any Canvas link works.", small: true)
            GlassField(placeholder: "canvas.yourschool.edu", text: $flow.schoolTyped) { if flow.chooseSchool() { flow.next() } }
                .frame(maxWidth: 360)
            problem
            Buttons {
                Button("that's my school") { if flow.chooseSchool() { flow.next() } }.welcomePrimary().disabled(flow.schoolTyped.isEmpty)
            }
            if flow.only == nil { Button("my school doesn't use Canvas") { flow.step = .extras }.buttonStyle(.plain).font(Typeface.sans(12)).foregroundStyle(.white.opacity(0.4)) }
        }
    }

    private var connectStep: some View {
        VStack(spacing: 14) {
            if flow.canvasState == .waiting {
                Said2(text: "this is your school's own Canvas login. log in here and I'll take it from there. it stays private on this Mac.", small: true)
                CanvasWebView(canvas: model.canvas)
                    .frame(width: 640, height: 400)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(.white.opacity(0.12), lineWidth: 1))
                    .onAppear { model.canvasEmbedded = true }
                    .onDisappear { model.canvasEmbedded = false }
                Button("got an access token after all? use it instead") { flow.useTokenPath() }.buttonStyle(.plain).font(Typeface.sans(12)).foregroundStyle(.white.opacity(0.4))
            } else if flow.canvasState == .checking {
                Said2(big: "you're in. finding your classes…")
            } else {
                TokenGuide(flow: flow)
            }
        }
    }

    private var classesStep: some View {
        VStack(spacing: 14) {
            if flow.only == "calendar" {
                Said2(big: flow.calendarFound ? "got your calendar." : "grabbing your Canvas calendar…")
                if flow.calendarFound { Said2(text: "every due date on it is in your plan now.", small: true) }
                problem
                if flow.problemText != nil { Buttons { Button("connect Canvas") { flow.only = "canvas"; flow.step = .school }.welcomePrimary() } }
            } else {
                Said2(big: "here's what I found.")
                Said2(text: "these are your classes this term. uncheck anything that isn't really a class.", small: true)
                ScrollView {
                    VStack(spacing: 6) {
                        ForEach($flow.courses) { $c in
                            Button { c.picked.toggle() } label: {
                                HStack(spacing: 12) {
                                    Image(systemName: c.picked ? "checkmark.circle.fill" : "circle").font(.system(size: 17)).foregroundStyle(c.picked ? .white : .white.opacity(0.3))
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(SetupFlow.friendlyName(c)).font(Typeface.sans(14, .medium)).foregroundStyle(.white.opacity(c.picked ? 0.95 : 0.5))
                                        Text([SetupFlow.shortID(c), c.term].filter { !$0.isEmpty }.joined(separator: Theme.sep)).font(Typeface.sans(11.5)).foregroundStyle(.white.opacity(0.4))
                                    }
                                    Spacer()
                                }
                                .padding(.horizontal, 14).padding(.vertical, 10)
                                .background(.white.opacity(c.picked ? 0.08 : 0.03), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .frame(maxWidth: 460, maxHeight: 280)
                problem
                Buttons { Button("these are my classes") { Task { await flow.saveClasses() } }.welcomePrimary().disabled(!flow.courses.contains { $0.picked }) }
            }
        }
        .task { if flow.only == "calendar" { await flow.calendarOnly() } }
    }

    private var extrasStep: some View {
        VStack(spacing: 16) {
            if flow.only == nil {
                Said2(big: flow.calendarFound ? "got your classes, and your Canvas calendar too." : "got your classes.")
                Said2(text: "one more place I can look, so nothing slips by: some professors only announce things by email.", small: true)
            } else {
                Said2(big: "let's add your school email.")
            }
            MailCard(flow: flow).frame(maxWidth: 460)
            Buttons {
                if flow.mailConnected != nil { Button(flow.only == nil ? "next" : "done") { if flow.only == nil { flow.next() } else { flow.finished() } }.welcomePrimary() }
                else { Button(flow.only == nil ? "skip for now" : "not now") { if flow.only == nil { flow.next() } else { flow.finished() } }.welcomeSecondary() }
            }
        }
    }

    private var phoneStep: some View {
        VStack(spacing: 16) {
            Said2(big: "want me in your pocket?")
            Said2(text: "send me notes from class, like \"test moved to friday\" or \"missed lecture\". I'll fix your plan before you're home.", small: true)
            QRCode(url: GenesisLinks.iPhoneApp).frame(width: 150, height: 150)
                .padding(12).background(.white, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            Text("point your iPhone camera here").font(Typeface.sans(12)).foregroundStyle(.white.opacity(0.5))
            Buttons {
                Button("maybe later") { flow.next() }.welcomeSecondary()
                Button("got it") { flow.next() }.welcomePrimary()
            }
        }
    }

    private var notifyStep: some View {
        VStack(spacing: 16) {
            Said2(big: "can I tap you on the shoulder?")
            Said2(text: "only when it matters: when today's ready, or something's due soon.", small: true)
            Buttons {
                Button("not now") { flow.next() }.welcomeSecondary()
                Button("sure") { model.enableNotifications(); flow.next() }.welcomePrimary()
            }
        }
    }

    private var doneStep: some View {
        VStack(spacing: 16) {
            if flow.only != nil {
                Said2(big: "all set.")
                Buttons { Button("done") { flow.finish() }.welcomePrimary() }
            } else {
                Said2(big: "that's everything\(flow.hi).")
                Said2(text: model.plugins.contains("canvas")
                      ? "I'm reading your classes now. the first time takes a few minutes, so go grab some water. I'll have today ready when you're back."
                      : "whenever you're ready, add Canvas in Settings and I'll build your first plan. until then, I'm here.", small: true)
                Buttons(delay: 1.2) { Button("see you in a bit") { flow.finish() }.welcomePrimary() }
            }
        }
    }

    @ViewBuilder private var problem: some View {
        if let p = flow.problemText {
            Text(p).font(Typeface.sans(12.5)).foregroundStyle(Color(red: 1, green: 0.72, blue: 0.6)).multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
        }
    }
}

// MARK: - Pieces

/// Genesis's words in the welcome: large and quiet, fading in.
private struct Said2: View {
    var big: String? = nil
    var text: String = ""
    var small = false
    var delay: Double = 0
    @State private var shown = false
    var body: some View {
        Group {
            if let big { Text(big).font(Typeface.serif(36)).foregroundStyle(.white) }
            else { Text(text).font(small ? Typeface.sans(15) : Typeface.serif(28)).foregroundStyle(.white.opacity(small ? 0.66 : 0.95)).lineSpacing(3) }
        }
        .multilineTextAlignment(.center)
        .fixedSize(horizontal: false, vertical: true)
        .opacity(shown ? 1 : 0).offset(y: shown ? 0 : 6)
        .onAppear { withAnimation(.easeOut(duration: 0.9).delay(delay)) { shown = true } }
    }
}

private struct Buttons<Content: View>: View {
    var delay: Double = 0.3
    @ViewBuilder var content: Content
    @State private var shown = false
    var body: some View {
        HStack(spacing: 12) { content }
            .padding(.top, 8)
            .opacity(shown ? 1 : 0)
            .onAppear { withAnimation(.easeOut(duration: 0.6).delay(delay)) { shown = true } }
    }
}

/// A text field made of glass.
struct GlassField: View {
    var placeholder: String
    @Binding var text: String
    var secure = false
    var submit: () -> Void
    @FocusState private var focused: Bool
    var body: some View {
        Group {
            if secure { SecureField(placeholder, text: $text) } else { TextField(placeholder, text: $text) }
        }
        .textFieldStyle(.plain)
        .font(Typeface.sans(16))
        .multilineTextAlignment(.center)
        .focused($focused)
        .onSubmit(submit)
        .padding(.horizontal, 20).padding(.vertical, 13)
        .background(.ultraThinMaterial, in: Capsule())
        .background(.white.opacity(focused ? 0.08 : 0.04), in: Capsule())
        .overlay(Capsule().strokeBorder(.white.opacity(focused ? 0.35 : 0.14), lineWidth: 1))
        .animation(.easeOut(duration: 0.2), value: focused)
        .onAppear { DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { focused = true } }
    }
}

private struct ChoiceCard: View {
    var title: String
    var detail: String
    var recommended = false
    var action: () -> Void
    @State private var hover = false
    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Text(title).font(Typeface.sans(15, .medium)).foregroundStyle(.white)
                        if recommended { Text("easiest").font(Typeface.sans(10.5, .medium)).foregroundStyle(.black).padding(.horizontal, 7).padding(.vertical, 2).background(.white.opacity(0.85), in: Capsule()) }
                    }
                    Text(detail).font(Typeface.sans(12.5)).foregroundStyle(.white.opacity(0.55)).fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundStyle(.white.opacity(hover ? 0.8 : 0.35))
            }
            .padding(16)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .background(.white.opacity(hover ? 0.08 : 0.03), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(.white.opacity(hover ? 0.3 : 0.12), lineWidth: 1))
            .contentShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .buttonStyle(.plain)
        .onHover { h in withAnimation(.easeOut(duration: 0.15)) { hover = h } }
    }
}

/// School email, step by step: address, then exactly where to make an app password.
private struct MailCard: View {
    @ObservedObject var flow: SetupFlow
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                Image(systemName: "envelope").font(.system(size: 18)).foregroundStyle(.white.opacity(0.8))
                VStack(alignment: .leading, spacing: 2) {
                    Text("school email").font(Typeface.sans(14.5, .medium)).foregroundStyle(.white)
                    Text("read-only. I never send, delete or mark anything.").font(Typeface.sans(12)).foregroundStyle(.white.opacity(0.5))
                }
                Spacer()
                if flow.mail == .idle { Button("connect") { withAnimation { flow.mail = .open } }.welcomeSecondary() }
                else if flow.mailConnected != nil { Image(systemName: "checkmark.circle.fill").foregroundStyle(.white) }
            }
            if flow.mail != .idle, flow.mailConnected == nil {
                GlassField(placeholder: "you@school.edu", text: $flow.mailAddress) {}
                    .onChange(of: flow.mailAddress) { _, _ in flow.guessProvider() }
                Text(flow.mailProvider.help).font(Typeface.sans(12)).foregroundStyle(.white.opacity(0.55)).fixedSize(horizontal: false, vertical: true)
                if let page = flow.mailProvider.passwordPage { Button("make an app password") { NSWorkspace.shared.open(page) }.welcomeSecondary() }
                GlassField(placeholder: "app password", text: $flow.mailPassword, secure: true) { flow.connectMail() }
                HStack {
                    Picker("", selection: $flow.mailProvider) { ForEach(MailProvider.allCases.filter { $0 != .other }) { Text($0.label).tag($0) } }.labelsHidden().frame(width: 190)
                    Spacer()
                    Button(flow.mail == .checking ? "checking…" : "connect") { flow.connectMail() }.welcomePrimary().disabled(flow.mail == .checking)
                }
                if let p = flow.mailProblem { Text(p).font(Typeface.sans(12)).foregroundStyle(Color(red: 1, green: 0.72, blue: 0.6)).fixedSize(horizontal: false, vertical: true) }
            }
            if let a = flow.mailConnected { Text("connected: " + a).font(Typeface.sans(12)).foregroundStyle(.white.opacity(0.6)) }
        }
        .padding(16)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(.white.opacity(0.12), lineWidth: 1))
    }
}

/// A QR code a phone camera can open.
struct QRCode: View {
    var url: URL
    var body: some View {
        if let image = Self.make(url.absoluteString) { Image(nsImage: image).interpolation(.none).resizable().scaledToFit() }
    }
    static func make(_ text: String) -> NSImage? {
        let f = CIFilter.qrCodeGenerator(); f.message = Data(text.utf8); f.correctionLevel = "M"
        guard let out = f.outputImage?.transformed(by: CGAffineTransform(scaleX: 10, y: 10)) else { return nil }
        let rep = NSCIImageRep(ciImage: out); let img = NSImage(size: rep.size); img.addRepresentation(rep); return img
    }
}

extension MailProvider {
    var passwordPage: URL? {
        switch self {
        case .gmail: return URL(string: "https://myaccount.google.com/apppasswords")
        case .icloud: return URL(string: "https://account.apple.com/account/manage")
        case .outlook: return URL(string: "https://account.microsoft.com/security")
        case .yahoo: return URL(string: "https://login.yahoo.com/account/security")
        case .other: return nil
        }
    }
}

// MARK: - Buttons for the black window: liquid glass, bright enough to read on black.
extension View {
    func welcomePrimary() -> some View { buttonStyle(WelcomeButtonStyle(primary: true)) }
    func welcomeSecondary() -> some View { buttonStyle(WelcomeButtonStyle(primary: false)) }
}

struct WelcomeButtonStyle: ButtonStyle {
    var primary: Bool
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Typeface.sans(14, primary ? .semibold : .medium))
            .foregroundStyle(primary ? Color.black : Color.white)
            .padding(.horizontal, 20).padding(.vertical, 10)
            .background(Capsule().fill(primary ? Color.white.opacity(configuration.isPressed ? 0.78 : 0.94) : Color.white.opacity(configuration.isPressed ? 0.22 : 0.12)))
            .background(.ultraThinMaterial, in: Capsule())
            // a thin liquid-glass rim: brighter on top, like light catching the edge
            .overlay(Capsule().strokeBorder(LinearGradient(colors: [.white.opacity(primary ? 0.9 : 0.45), .white.opacity(0.08)], startPoint: .top, endPoint: .bottom), lineWidth: 1))
            .shadow(color: .white.opacity(primary ? 0.18 : 0), radius: 14)
            .opacity(enabled ? 1 : 0.4)
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
    }
}

// MARK: - The access token, drawn

/// How Genesis connects to Canvas: an access token, a read-only key the student makes in their
/// own Canvas settings. The guide holds their hand through it with four white line sketches on
/// black, each drawing itself in with a pulse on exactly what to click. Schools that turn tokens
/// off get the school's own login page instead.
private struct TokenGuide: View {
    @ObservedObject var flow: SetupFlow
    private static let words: [(big: String, text: String)] = [
        ("", ""),
        ("open your Canvas settings.", "the button below takes you right there. log in first if Canvas asks. (it's the same as clicking Account on the far left, then Settings.)"),
        ("find Approved Integrations.", "scroll down your settings page until you see it, then click + New Access Token."),
        ("call it Genesis.", "type Genesis where it says Purpose. you can leave the date empty. then click Generate Token."),
        ("copy it, paste it here.", "Canvas only shows it once, so copy the whole long code now. paste it below and I'll do the rest."),
    ]

    var body: some View {
        VStack(spacing: 12) {
            if flow.guide == 0 { hello } else { step(flow.guide) }
        }
        .animation(.easeOut(duration: 0.3), value: flow.guide)
    }

    private var hello: some View {
        VStack(spacing: 14) {
            Said2(big: "let's connect your Canvas.")
            Said2(text: "I use a Canvas access token. think of it as a key that only reads: your classes, due dates and grades, never anything you'd turn in. it stays in your Mac's Keychain, and making one takes about a minute. I'll show you exactly where.", small: true)
            Buttons {
                Button("I already have one") { go(4) }.welcomeSecondary()
                Button("show me how") { go(1) }.welcomePrimary()
            }
            fallback("my school doesn't let me make one")
        }
    }

    @ViewBuilder private func step(_ n: Int) -> some View {
        SketchCard(step: n).id(n).frame(maxWidth: 460)
        Said2(big: Self.words[n].big).id("big\(n)")
        Said2(text: Self.words[n].text, small: true).id("text\(n)")
        switch n {
        case 1:
            Buttons(delay: 0.1) {
                Button("back") { go(0) }.welcomeSecondary()
                Button("open my Canvas settings") {
                    if let url = URL(string: "https://\(flow.host)/profile/settings") { NSWorkspace.shared.open(url) }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.9) { go(2) }
                }.welcomePrimary()
            }
        case 2:
            Buttons(delay: 0.1) {
                Button("back") { go(1) }.welcomeSecondary()
                Button("I clicked it") { go(3) }.welcomePrimary()
            }
            fallback("I don't see New Access Token")
        case 3:
            Buttons(delay: 0.1) {
                Button("back") { go(2) }.welcomeSecondary()
                Button("I see a long code") { go(4) }.welcomePrimary()
            }
        default:
            GlassField(placeholder: "paste the token here", text: $flow.tokenTyped, secure: true) { Task { await flow.useToken() } }
                .frame(maxWidth: 380)
                .onAppear(perform: catchCopied)
                .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in catchCopied() }
            if let p = flow.problemText {
                Text(p).font(Typeface.sans(12.5)).foregroundStyle(.white.opacity(0.85)).multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            }
            Buttons(delay: 0.1) {
                Button("back") { go(3) }.welcomeSecondary()
                Button("connect") { Task { await flow.useToken() } }.welcomePrimary().disabled(flow.tokenTyped.isEmpty)
            }
            fallback("it won't take my token")
        }
    }

    /// No token at this school: the alternative is the school's own login page.
    private func fallback(_ title: String) -> some View {
        VStack(spacing: 4) {
            Button { flow.startSignIn() } label: {
                Text(title + "  ›").font(Typeface.sans(12.5, .medium)).foregroundStyle(.white.opacity(0.55))
            }
            .buttonStyle(.plain)
            Text("no problem. some schools turn tokens off. I'll take you to your school's login page instead.")
                .font(Typeface.sans(11)).foregroundStyle(.white.opacity(0.32)).multilineTextAlignment(.center)
        }
        .padding(.top, 6)
    }

    private func go(_ n: Int) { flow.canvasState = .idle; flow.guide = n }

    /// Coming back from Canvas with the token already copied: it's waiting in the box.
    private func catchCopied() {
        guard flow.tokenTyped.isEmpty, let s = NSPasteboard.general.string(forType: .string)?.trimmingCharacters(in: .whitespacesAndNewlines),
              s.range(of: "^[0-9]+~[A-Za-z0-9]{30,}$", options: .regularExpression) != nil else { return }
        flow.tokenTyped = s
    }
}

/// One drawn step: thin white lines on black, a faint grid, a slow scan line, corner brackets,
/// and a pulse around the thing to click.
private struct SketchCard: View {
    var step: Int
    @State private var drawn: CGFloat = 0
    @State private var pulse = false
    @State private var scan = false
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        let d = Drawing.of(step)
        GeometryReader { g in
            let w = g.size.width, h = g.size.height
            ZStack(alignment: .topLeading) {
                Canvas { ctx, size in
                    var y: CGFloat = 8
                    while y < size.height { var x: CGFloat = 8
                        while x < size.width { ctx.fill(Path(ellipseIn: CGRect(x: x, y: y, width: 1, height: 1)), with: .color(.white.opacity(0.09))); x += 16 }
                        y += 16 }
                }
                Sketch(marks: d.faint).trim(from: 0, to: drawn)
                    .stroke(.white.opacity(0.3), style: StrokeStyle(lineWidth: 1, lineCap: .round, lineJoin: .round))
                Sketch(marks: d.bright).trim(from: 0, to: drawn)
                    .stroke(.white.opacity(0.92), style: StrokeStyle(lineWidth: 1.3, lineCap: .round, lineJoin: .round))
                ForEach(d.labels) { l in
                    Text(l.text).font(Typeface.mono(9.5, l.bright ? .medium : .regular))
                        .foregroundStyle(.white.opacity(l.bright ? 0.95 : 0.45))
                        .fixedSize()
                        .position(x: l.x * w, y: l.y * h)
                }
                .opacity(drawn)
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .stroke(.white, lineWidth: 1.2)
                    .frame(width: d.target.width * w + 10, height: d.target.height * h + 10)
                    .scaleEffect(pulse ? 1.18 : 1)
                    .opacity(drawn < 1 ? 0 : (pulse ? 0 : 0.9))
                    .position(x: d.target.midX * w, y: d.target.midY * h)
                Rectangle().fill(LinearGradient(colors: [.clear, .white.opacity(0.10), .clear], startPoint: .leading, endPoint: .trailing))
                    .frame(width: w, height: 1)
                    .offset(y: scan ? h : 0)
                    .opacity(reduce ? 0 : 1)
            }
        }
        .frame(height: 150)
        .padding(14)
        .background(Color.black)
        .overlay(CornerBrackets().stroke(.white.opacity(0.55), lineWidth: 1))
        .overlay(alignment: .topTrailing) {
            Text(String(format: "%02d / 04", step)).font(Typeface.mono(10)).foregroundStyle(.white.opacity(0.4)).padding(.horizontal, 10).padding(.vertical, 6)
        }
        .onAppear {
            if reduce { drawn = 1; return }
            withAnimation(.easeInOut(duration: 1.5)) { drawn = 1 }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                withAnimation(.easeOut(duration: 1.5).repeatForever(autoreverses: false)) { pulse = true }
            }
            withAnimation(.linear(duration: 5).repeatForever(autoreverses: false)) { scan = true }
        }
    }
}

private struct CornerBrackets: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path(); let l: CGFloat = 14
        for (c, dx, dy) in [(CGPoint(x: r.minX, y: r.minY), 1.0, 1.0), (CGPoint(x: r.maxX, y: r.minY), -1.0, 1.0),
                            (CGPoint(x: r.minX, y: r.maxY), 1.0, -1.0), (CGPoint(x: r.maxX, y: r.maxY), -1.0, -1.0)] {
            p.move(to: CGPoint(x: c.x + dx * l, y: c.y)); p.addLine(to: c); p.addLine(to: CGPoint(x: c.x, y: c.y + dy * l))
        }
        return p
    }
}

private enum Mark {
    case box(CGFloat, CGFloat, CGFloat, CGFloat, CGFloat = 4)
    case line(CGFloat, CGFloat, CGFloat, CGFloat)
    case ring(CGFloat, CGFloat, CGFloat)          // center, radius as a share of the height
    case arrow(CGFloat, CGFloat, CGFloat, CGFloat)
}

private struct SketchLabel: Identifiable {
    var text: String; var x: CGFloat; var y: CGFloat; var bright = false
    var id: String { text + "\(x)\(y)" }
}

private struct Sketch: Shape {
    var marks: [Mark]
    func path(in r: CGRect) -> Path {
        var p = Path()
        func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: r.minX + x * r.width, y: r.minY + y * r.height) }
        for m in marks {
            switch m {
            case let .box(x, y, w, h, c):
                p.addRoundedRect(in: CGRect(origin: pt(x, y), size: CGSize(width: w * r.width, height: h * r.height)), cornerSize: CGSize(width: c, height: c))
            case let .line(a, b, c, d):
                p.move(to: pt(a, b)); p.addLine(to: pt(c, d))
            case let .ring(x, y, rad):
                let c = pt(x, y), k = rad * r.height
                p.addEllipse(in: CGRect(x: c.x - k, y: c.y - k, width: k * 2, height: k * 2))
            case let .arrow(a, b, c, d):
                let s = pt(a, b), e = pt(c, d), ang = atan2(e.y - s.y, e.x - s.x)
                p.move(to: s); p.addLine(to: e)
                for t in [ang + .pi * 0.8, ang - .pi * 0.8] { p.move(to: e); p.addLine(to: CGPoint(x: e.x + 7 * cos(t), y: e.y + 7 * sin(t))) }
            }
        }
        return p
    }
}

/// The four pictures. Coordinates are shares of the card, so they hold at any size.
private struct Drawing {
    var bright: [Mark]; var faint: [Mark]; var labels: [SketchLabel]; var target: CGRect

    private static let window: [Mark] = [.box(0.01, 0.02, 0.98, 0.96, 8), .line(0.01, 0.16, 0.99, 0.16),
                                         .ring(0.04, 0.09, 0.022), .ring(0.065, 0.09, 0.022), .ring(0.09, 0.09, 0.022)]

    static func of(_ step: Int) -> Drawing {
        switch step {
        case 1:   // Canvas: Account on the far left, then Settings
            return Drawing(
                bright: window + [.line(0.13, 0.16, 0.13, 0.98), .ring(0.07, 0.27, 0.05),
                                  .box(0.15, 0.21, 0.29, 0.7, 6), .ring(0.21, 0.34, 0.06), .box(0.17, 0.63, 0.25, 0.1, 4)],
                faint: [.ring(0.07, 0.48, 0.04), .ring(0.07, 0.63, 0.04), .ring(0.07, 0.78, 0.04),
                        .line(0.27, 0.31, 0.41, 0.31), .line(0.27, 0.37, 0.37, 0.37), .line(0.17, 0.5, 0.41, 0.5), .line(0.17, 0.82, 0.36, 0.82),
                        .line(0.5, 0.3, 0.93, 0.3), .line(0.5, 0.42, 0.86, 0.42), .line(0.5, 0.54, 0.9, 0.54), .line(0.5, 0.66, 0.8, 0.66), .line(0.5, 0.78, 0.88, 0.78)],
                labels: [SketchLabel(text: "Canvas", x: 0.5, y: 0.09), SketchLabel(text: "Account", x: 0.07, y: 0.37),
                         SketchLabel(text: "Settings", x: 0.24, y: 0.68, bright: true)],
                target: CGRect(x: 0.17, y: 0.63, width: 0.25, height: 0.1))
        case 2:   // Settings: scroll to Approved Integrations, + New Access Token
            return Drawing(
                bright: window + [.line(0.05, 0.52, 0.6, 0.52), .box(0.66, 0.4, 0.29, 0.13, 4), .box(0.966, 0.46, 0.014, 0.2, 3),
                                  .arrow(0.92, 0.22, 0.92, 0.33)],
                faint: [.line(0.05, 0.25, 0.5, 0.25), .line(0.05, 0.31, 0.4, 0.31),
                        .line(0.05, 0.64, 0.94, 0.64), .line(0.05, 0.74, 0.94, 0.74), .line(0.05, 0.84, 0.94, 0.84), .line(0.4, 0.58, 0.4, 0.9),
                        .line(0.973, 0.2, 0.973, 0.94)],
                labels: [SketchLabel(text: "Settings", x: 0.5, y: 0.09), SketchLabel(text: "scroll", x: 0.86, y: 0.27),
                         SketchLabel(text: "Approved Integrations", x: 0.2, y: 0.46, bright: true),
                         SketchLabel(text: "+ New Access Token", x: 0.805, y: 0.465, bright: true)],
                target: CGRect(x: 0.66, y: 0.4, width: 0.29, height: 0.13))
        case 3:   // The little window: Purpose "Genesis", date empty, Generate Token
            return Drawing(
                bright: [.box(0.2, 0.08, 0.6, 0.86, 8), .box(0.37, 0.33, 0.37, 0.13, 4), .box(0.37, 0.52, 0.37, 0.13, 4), .box(0.5, 0.74, 0.24, 0.12, 4)],
                faint: window + [.line(0.2, 0.25, 0.8, 0.25), .line(0.03, 0.4, 0.17, 0.4), .line(0.03, 0.55, 0.15, 0.55), .line(0.83, 0.45, 0.97, 0.45)],
                labels: [SketchLabel(text: "New Access Token", x: 0.5, y: 0.17, bright: true),
                         SketchLabel(text: "Purpose", x: 0.29, y: 0.395), SketchLabel(text: "Genesis", x: 0.44, y: 0.395, bright: true),
                         SketchLabel(text: "Expires", x: 0.29, y: 0.585), SketchLabel(text: "(leave empty)", x: 0.6, y: 0.585),
                         SketchLabel(text: "Generate Token", x: 0.62, y: 0.8, bright: true)],
                target: CGRect(x: 0.5, y: 0.74, width: 0.24, height: 0.12))
        default:  // The token: copy the long code, paste it into Genesis
            return Drawing(
                bright: [.box(0.1, 0.06, 0.8, 0.5, 8), .box(0.14, 0.27, 0.72, 0.16, 4), .arrow(0.5, 0.59, 0.5, 0.74), .box(0.3, 0.78, 0.4, 0.16, 15)],
                faint: [.line(0.1, 0.2, 0.9, 0.2)],
                labels: [SketchLabel(text: "Token", x: 0.17, y: 0.13), SketchLabel(text: "copy  ⌘C", x: 0.82, y: 0.13),
                         SketchLabel(text: "7~Ah3kQ9xR2mZp8L0vWc5nTj4bYe6Fs1GuNq", x: 0.5, y: 0.35, bright: true),
                         SketchLabel(text: "paste here  ⌘V", x: 0.5, y: 0.86, bright: true)],
                target: CGRect(x: 0.14, y: 0.27, width: 0.72, height: 0.16))
        }
    }
}
