import SwiftUI
import PDFKit
import ImageIO
import AppKit
import Darwin
import UserNotifications

// MARK: - Data contracts (written by the Python side)

struct PromptBlock: Codable, Hashable {
    var kind: String
    var text: String
    var language: String?
}

struct TaskSource: Codable, Hashable, Identifiable {
    var label: String
    var location: String?
    var pages: [Int]?
    var section: String?
    var origin: String?
    var captured_at: String?
    var snapshot: String?
    var role: String?
    var search: String?
    var id: String { label + (section ?? "") + (pages?.map(String.init).joined(separator: ",") ?? "") }
    var localURL: URL? {
        if let s = snapshot, FileManager.default.fileExists(atPath: s) { return URL(fileURLWithPath: s) }
        if let l = location, l.hasPrefix("/"), FileManager.default.fileExists(atPath: l) { return URL(fileURLWithPath: l) }
        return nil
    }
    var isPDF: Bool { localURL?.pathExtension.lowercased() == "pdf" }
    var pageLabel: String? {
        guard let p = pages, !p.isEmpty else { return nil }
        if p.count == 1 { return "p. \(p[0])" }
        let sorted = p.sorted()
        if sorted.last! - sorted.first! == sorted.count - 1 { return "pp. \(sorted.first!)–\(sorted.last!)" }
        return "pp. " + sorted.map(String.init).joined(separator: ", ")
    }
}

struct StudyTask: Codable, Identifiable, Hashable {
    var id: String
    var number: Int
    var title: String
    var body: String?
    var course: String
    var course_id: String?
    var kind: String?
    var exercise_id: String?
    var skill_ids: [String]?
    var reason: String?
    var sources: [TaskSource]?
    var prompt_blocks: [PromptBlock]?
    var teaching_blocks: [PromptBlock]?
    var example_blocks: [PromptBlock]?
    var hint_blocks: [PromptBlock]?
    var question: String?
    var steps: [String]?
    var aids: String?
    var done_when: String?
    var cue: String?
    var answer_type: String?
    var origin: String?
    var format_match: String?
    var problem_label: String?
    var mode: String?
    var language: String?
    var estimated_minutes: Int?
    var estimate_basis: String?
    var context_addition: Bool?
    var parent: String?
    var answer_format: String?

    enum CodingKeys: String, CodingKey {
        case id, number, title, body, course, course_id, kind, exercise_id, skill_ids, reason, sources, prompt_blocks, teaching_blocks, example_blocks, hint_blocks
        case question, steps, aids, done_when, cue, answer_type, origin, format_match, problem_label, mode, language, estimated_minutes, estimate_basis, context_addition, parent, answer_format
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func str(_ k: CodingKeys) -> String? {
            if let s = try? c.decode(String.self, forKey: k) { return s }
            if let a = try? c.decode([String].self, forKey: k) { return a.joined(separator: ", ") }
            if let i = try? c.decode(Int.self, forKey: k) { return String(i) }
            return nil
        }
        id = try c.decode(String.self, forKey: .id)
        number = (try? c.decode(Int.self, forKey: .number)) ?? 0
        title = str(.title) ?? "Task"
        body = str(.body); course = str(.course) ?? ""; course_id = str(.course_id); kind = str(.kind); exercise_id = str(.exercise_id)
        skill_ids = try? c.decode([String].self, forKey: .skill_ids); reason = str(.reason)
        sources = (try? c.decode([Lossy<TaskSource>].self, forKey: .sources))?.compactMap { $0.value }
        prompt_blocks = (try? c.decode([Lossy<PromptBlock>].self, forKey: .prompt_blocks))?.compactMap { $0.value }
        teaching_blocks = (try? c.decode([Lossy<PromptBlock>].self, forKey: .teaching_blocks))?.compactMap { $0.value }
        example_blocks = (try? c.decode([Lossy<PromptBlock>].self, forKey: .example_blocks))?.compactMap { $0.value }
        hint_blocks = (try? c.decode([Lossy<PromptBlock>].self, forKey: .hint_blocks))?.compactMap { $0.value }
        question = str(.question); steps = try? c.decode([String].self, forKey: .steps); aids = str(.aids); done_when = str(.done_when); cue = str(.cue)
        answer_type = str(.answer_type); origin = str(.origin); format_match = str(.format_match); problem_label = str(.problem_label); mode = str(.mode); language = str(.language)
        estimated_minutes = try? c.decode(Int.self, forKey: .estimated_minutes); estimate_basis = str(.estimate_basis)
        context_addition = try? c.decode(Bool.self, forKey: .context_addition); parent = str(.parent); answer_format = str(.answer_format)
    }

    var exerciseID: String { exercise_id ?? id }
    var courseID: String { course_id ?? course }
    var minutes: Int { estimated_minutes ?? 15 }
    var problemSource: TaskSource? { sources?.first { $0.role == "problem" } }
    var readSources: [TaskSource] { sources?.filter { $0.role == "read" } ?? [] }
    var modeLabel: String {
        switch mode {
        case "learn": return "Learn"
        case "repair": return "Fix a mistake"
        case "retrieval": return "Review"
        case "mock": return "Exam set"
        case "prep": return "Prepare"
        case "catch_up": return "Catch up"
        case "diagnose": return "Check"
        default: return parent != nil ? "Retry" : "Practice"
        }
    }
    var originLabel: String? {
        switch origin {
        case "exact_source": return "From your course materials"
        case "adapted_source": return "Adapted from your course materials"
        case "original_format_matched": return "Original, in your professor's format"
        default: return nil
        }
    }
}

struct Brief: Codable {
    var id: String
    var date: String
    var title: String
    var subtitle: String
    var tasks: [StudyTask]
    var generated_at: String
    var source_limits: String?

    enum CodingKeys: String, CodingKey { case id, date, title, subtitle, tasks, generated_at, source_limits }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        date = try c.decode(String.self, forKey: .date)
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        subtitle = (try? c.decode(String.self, forKey: .subtitle)) ?? ""
        generated_at = (try? c.decode(String.self, forKey: .generated_at)) ?? ""
        source_limits = try? c.decode(String.self, forKey: .source_limits)
        // Decode tasks one by one: a single malformed task is skipped, not the whole plan.
        tasks = ((try? c.decode([Lossy<StudyTask>].self, forKey: .tasks)) ?? []).compactMap { $0.value }
    }
}

struct Lossy<T: Decodable>: Decodable {
    let value: T?
    init(from decoder: Decoder) throws { value = try? T(from: decoder) }
}

struct RequestProgress: Codable { var step: String; var fraction: Double; var label: String? }

struct PipelineRequest: Codable {
    var id: String
    var status: String
    var requested_at: String
    var detail: String?
    var manual: Bool?
    var stage: String?
    var policy_id: String?
    var progress: RequestProgress?
    var finished_at: String?
}

struct SourceStatus: Codable { var status: String; var detail: String?; var checked_at: String?; var request_id: String? }
struct PipelineEvent: Codable { var id: String; var title: String; var body: String }

struct PipelineState: Codable {
    var request: PipelineRequest?
    var sources: [String: SourceStatus]
    var events: [PipelineEvent]
    var brief: Brief?
    var last_successful_sync: String?
}

struct Unreadable: Hashable { var reason: String; var tips: [String]; var examples: [String] }

/// Turns a dropped image or PDF into page images, downscaled to a size the grader reads well.
enum PageImages {
    static func images(from url: URL) -> [CGImage] {
        if url.pathExtension.lowercased() == "pdf", let doc = PDFDocument(url: url) {
            return (0..<min(doc.pageCount, 8)).compactMap { i in doc.page(at: i).flatMap { render($0) } }
        }
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil) else { return [] }
        let opts: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceCreateThumbnailWithTransform: true,
                                     kCGImageSourceThumbnailMaxPixelSize: 2200]
        return CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary).map { [$0] } ?? []
    }
    static func render(_ page: PDFPage) -> CGImage? {
        let box = page.bounds(for: .mediaBox)
        let scale = min(2.5, 2200 / max(box.width, box.height))
        let w = Int(box.width * scale), h = Int(box.height * scale)
        guard w > 0, h > 0, let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                                                space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return nil }
        ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1)); ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
        ctx.scaleBy(x: scale, y: scale); ctx.translateBy(x: -box.origin.x, y: -box.origin.y)
        page.draw(with: .mediaBox, to: ctx)
        return ctx.makeImage()
    }
    static func writePNG(_ image: CGImage, to url: URL) -> Bool {
        guard let dest = CGImageDestinationCreateWithURL(url as CFURL, "public.png" as CFString, 1, nil) else { return false }
        CGImageDestinationAddImage(dest, image, nil)
        return CGImageDestinationFinalize(dest)
    }
}

struct Attempt: Codable, Hashable {
    var attempt_id: String
    var at: String
    var outcome: String
    var score: Double?
    var feedback: String
    var specific_error: String?
    var misconception: String?
    var next_step: String?
}

struct Feedback: Codable {
    var exercise_id: String
    var attempts: [Attempt]
    var latest: Attempt?
    var retry: StudyTask?
    var worked_solution: String?
    var correct: Bool { attempts.contains { $0.outcome == "correct" } }
}

struct OverviewEvent: Codable, Hashable { var name: String; var date: String; var days: Int; var exam: Bool; var overdue: Bool?; var course: String? }
struct WeakSkill: Codable, Hashable { var name: String; var error: String? }
struct CourseOverview: Codable, Identifiable {
    var id: String
    var label: String
    var title: String
    var grade: String?
    var low_exams: [String]
    var skills: [String: Int]
    var skill_total: Int
    var due_reviews: Int
    var events: [OverviewEvent]
    var weak: [WeakSkill]
    var priority: Double
}
struct Overview: Codable { var day: String; var courses: [CourseOverview]; var upcoming: [OverviewEvent] }

struct Chip: Codable, Hashable { var kind: String; var course: String?; var label: String }
struct ContextNote: Codable, Identifiable, Hashable { var id: String; var text: String; var expires_on: String; var chips: [Chip]; var source: String?; var effect: String? }
struct NotesFile: Codable { var notes: [ContextNote] }

/// plan: today | shared (another assessment's task covers it) | covered (earlier independent work)
/// | later (paced for a later day) | deferred (no room today; reason given) | not_written
struct CoverageTopic: Codable, Hashable { var title: String; var mode: String?; var exercise_id: String?; var plan: String?; var state: String?; var reason: String? }
struct CoverageItem: Codable, Identifiable, Hashable { var id: String; var course: String; var name: String; var date: String; var days: Int; var kind: String; var basis: String; var scope: String?; var certainty: String?; var topics: [CoverageTopic] }
struct DeferredItem: Codable, Hashable { var course: String; var title: String; var mode: String; var reason: String; var `for`: String? }
struct UndatedItem: Codable, Hashable { var course: String; var name: String; var source: String }
struct DateReport: Codable, Hashable { var course: String; var name: String; var date: String; var status: String; var official_date: String? }
struct Coverage: Codable { var day: String; var obligations: [CoverageItem]; var deferred: [DeferredItem]?; var undated: [UndatedItem]?; var reports: [DateReport]? }

struct SearchHit: Codable, Identifiable, Hashable { var path: String; var course: String; var snippet: String; var id: String { path } }

// MARK: - Sync stages shown in the progress panel

struct SyncStage: Identifiable { var id: String; var label: String; var start: Double }
let syncStages: [SyncStage] = [
    .init(id: "sources", label: "Canvas", start: 0.0),
    .init(id: "supplements", label: "Professor site and calendar", start: 0.36),
    .init(id: "catalog", label: "Reading practice files", start: 0.42),
    .init(id: "facts", label: "Exam updates", start: 0.53),
    .init(id: "plan", label: "Choosing what to study", start: 0.58),
    .init(id: "write", label: "Writing and checking tasks", start: 0.6),
    .init(id: "publish", label: "Publishing", start: 0.96),
]

// MARK: - App model

@MainActor
final class AppModel: ObservableObject {
    @Published var state: PipelineState?
    @Published var overview: Overview?
    @Published var coverage: Coverage?
    @Published var feedback: [String: Feedback] = [:]
    @Published var notes: [ContextNote] = []
    @Published var drafts: [String: String] = [:]
    @Published var usedHelp: Set<String> = []
    @Published var grading: Set<String> = []
    @Published var gradeError: [String: String] = [:]
    @Published var unreadable: [String: Unreadable] = [:]
    @Published var attachments: [String: [String]] = [:]   // exercise id -> PNG pages of digital paper
    @Published var message = ""
    @Published var syncing = false
    @Published var connected = false
    @Published var workspace: String
    @Published var page: Page = .today
    @Published var openTask: StudyTask? { didSet { Companion.shared.taskChanged(openTask) } }
    @Published var farewell = UserDefaults.standard.bool(forKey: "farewell")
    @Published var canvasSignIn = false
    /// Plugins you've added (Settings › Plugins). Anything not here never runs or appears.
    @Published var plugins: Set<String> = []
    @Published var choosingPlugins = false

    func loadPlugins() {
        guard !workspace.isEmpty, let c = try? GenesisConfiguration.load(root: workspace) else { return }
        let on = Set(GenesisPlugin.catalog.map(\.id).filter { c.on($0) })
        if on != plugins { plugins = on }
        if !c.plugins_chosen && !choosingPlugins && ProcessInfo.processInfo.environment["GENESIS_TEST_WORKSPACE"] == nil { choosingPlugins = true }
    }

    func setPlugin(_ id: String, _ on: Bool) {
        var c = (try? GenesisConfiguration.load(root: workspace)) ?? GenesisConfiguration()
        c.plugins[id] = on
        if id == "professor_sites" && !on { c.cop3330_professor_enabled = nil }
        do { try c.save(root: workspace) } catch { message = error.localizedDescription; return }
        if on { plugins.insert(id) } else { plugins.remove(id) }
    }

    func finishPluginChoice() {
        var c = (try? GenesisConfiguration.load(root: workspace)) ?? GenesisConfiguration()
        c.plugins_chosen = true
        try? c.save(root: workspace)
        choosingPlugins = false
        // Canvas needs your classes before it can build a plan.
        if plugins.contains("canvas") && c.courses.isEmpty { message = "Add your classes in Settings › Accounts, then sync." }
    }
    @Published var searchHits: [SearchHit] = []
    @Published var appearance: String = UserDefaults.standard.string(forKey: "appearance") ?? "dark"

    enum Page: String, CaseIterable, Identifiable { case today, practice, progress, library; var id: String { rawValue } }

    let canvas = LocalCanvas()
    private var timer: Timer?
    private var reading = false
    private var runner: Process?
    private var seenEvents: Set<String> = []
    private var loadedOnce = false
    private var scoped: URL?

    var bridge: URL { URL(fileURLWithPath: workspace).appendingPathComponent("outputs/School HQ App/Bridge") }
    var outputs: URL { URL(fileURLWithPath: workspace).appendingPathComponent("outputs") }
    var brief: Brief? { state?.brief }
    var tasks: [StudyTask] { brief?.tasks.sorted { $0.number < $1.number } ?? [] }
    var busy: Bool { syncing || ["queued", "processing"].contains(state?.request?.status ?? "") }
    var syncFailed: Bool { state?.request?.status == "blocked" }

    init() {
        let bundled = Bundle.main.url(forResource: "workspace", withExtension: "txt").flatMap { try? String(contentsOf: $0, encoding: .utf8) }?.trimmingCharacters(in: .whitespacesAndNewlines)
        workspace = UserDefaults.standard.string(forKey: "schoolHQWorkspace") ?? bundled ?? ""
        if let bookmark = UserDefaults.standard.data(forKey: "schoolHQBookmark") {
            var stale = false
            if let url = try? URL(resolvingBookmarkData: bookmark, options: .withSecurityScope, relativeTo: nil, bookmarkDataIsStale: &stale) {
                scoped = url; _ = url.startAccessingSecurityScopedResource(); workspace = url.path
            }
        }
        do { workspace = try GenesisRuntime.prepare(preferred: workspace).path }
        catch { message = "Genesis could not prepare its local storage: \(error.localizedDescription)" }
        connected = GenesisRuntime.python != nil && !workspace.isEmpty && FileManager.default.fileExists(atPath: workspace + "/outputs/school_hq_app_bridge.py")
        if GenesisRuntime.python == nil { message = "This build is missing its Python runtime. Install a complete Genesis release." }
        if let data = UserDefaults.standard.dictionary(forKey: "drafts") as? [String: String] { drafts = data }
        if let data = UserDefaults.standard.dictionary(forKey: "answerPages") as? [String: [String]] {
            attachments = data.mapValues { $0.filter { FileManager.default.fileExists(atPath: $0) } }.filter { !$0.value.isEmpty }
        }
        if connected { reload(); refreshNotes(); runScript("school_hq_engine.py", ["overview"]) { _ in self.reload() } }
        timer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in Task { @MainActor in self?.reload() } }
        // Notes typed in the Genesis iPhone app arrive through iCloud Drive/Genesis/Notes.
        if connected { importPhoneNotes() }
        Companion.shared.attach(self)
        inboxTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in Task { @MainActor in self?.importPhoneNotes() } }
    }

    private var inboxTimer: Timer?

    /// iCloud Drive on this Mac: a folder chosen in Settings, the classic location, or the
    /// newer ~/Library/CloudStorage/iCloudDrive-* layout.
    var iCloudRoot: URL? {
        let fm = FileManager.default, home = fm.homeDirectoryForCurrentUser
        let config = outputs.appendingPathComponent("School HQ Study/phone-inbox.json")
        if let data = try? Data(contentsOf: config), let v = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let path = v["icloud_root"] as? String { return URL(fileURLWithPath: path) }
        let classic = home.appendingPathComponent("Library/Mobile Documents/com~apple~CloudDocs")
        if fm.fileExists(atPath: classic.path) { return classic }
        let storage = home.appendingPathComponent("Library/CloudStorage")
        return (try? fm.contentsOfDirectory(at: storage, includingPropertiesForKeys: nil))?.first { $0.lastPathComponent.hasPrefix("iCloudDrive") }
    }

    /// Imports notes typed in the Genesis iPhone app (iCloud Drive/Genesis/Notes/*.json) into
    /// Tell Genesis, and publishes the class list the phone shows. Runs in the app itself so
    /// macOS asks once for iCloud Drive access on behalf of Genesis.
    func importPhoneNotes() {
        if ProcessInfo.processInfo.environment["GENESIS_TEST_WORKSPACE"] != nil { return }
        guard connected else { return }
        let statusURL = bridge.appendingPathComponent("phone-inbox.json")
        func status(_ v: [String: Any]) {
            var v = v; v["checked_at"] = ISO8601DateFormatter().string(from: Date())
            try? JSONSerialization.data(withJSONObject: v, options: .prettyPrinted).write(to: statusURL, options: .atomic)
        }
        guard let root = iCloudRoot, FileManager.default.fileExists(atPath: root.path) else { status(["status": "icloud_drive_off", "imported": 0]); return }
        let folder = root.appendingPathComponent("Genesis"), notes = folder.appendingPathComponent("Notes"), done = notes.appendingPathComponent("Imported")
        do {
            try FileManager.default.createDirectory(at: done, withIntermediateDirectories: true)
            let courses: [[String: String]] = try GenesisConfiguration.load(root: workspace).courses.map { ["id": $0.id, "label": $0.label] }
            let list = folder.appendingPathComponent("courses.json")
            if (try? Data(contentsOf: list)).flatMap({ try? JSONSerialization.jsonObject(with: $0) as? [String: Any] })?["courses"] as? [[String: String]] != courses {
                try JSONSerialization.data(withJSONObject: ["schema": 1, "courses": courses], options: .prettyPrinted).write(to: list, options: .atomic)
            }
            // Notes arrive two ways: one JSON file per note in Genesis/Notes (folder access), or
            // files the "Genesis Note" shortcut saves into Genesis/ holding a JSON array of notes.
            let fm = FileManager.default
            let direct = try fm.contentsOfDirectory(at: notes, includingPropertiesForKeys: nil).filter { $0.pathExtension == "json" }
            let viaShortcut = (try? fm.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil))?
                .filter { ["json", "txt"].contains($0.pathExtension.lowercased()) && $0.lastPathComponent != "courses.json" } ?? []
            let files = direct + viaShortcut
            status(["status": "ok", "folder": folder.path, "imported": files.count])
            for file in files {
                guard let data = try? Data(contentsOf: file) else { continue }
                let parsed = try? JSONSerialization.jsonObject(with: data)
                var items: [[String: Any]] = (parsed as? [[String: Any]]) ?? ((parsed as? [String: Any]).map { [$0] } ?? [])
                if items.isEmpty, let raw = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty {
                    items = [["text": raw]]   // a plain-text note
                }
                let valid = items.filter { $0["text"] is String }
                guard !valid.isEmpty else { continue }
                var remaining = valid.count
                for note in valid {
                    var payload = note; payload["source"] = "iphone"
                    guard let body = try? JSONSerialization.data(withJSONObject: payload) else { remaining -= 1; continue }
                    runScript("school_hq_context.py", ["add"], stdin: body) { result in
                        remaining -= 1
                        if remaining == 0, result != nil {
                            try? fm.moveItem(at: file, to: done.appendingPathComponent(String(UUID().uuidString.prefix(8)) + "-" + file.lastPathComponent))
                        }
                        self.refreshNotes()
                    }
                }
            }
        } catch {
            status(["status": "permission_needed", "detail": "macOS blocked Genesis from iCloud Drive. Allow it when asked, or in System Settings › Privacy & Security › Files and Folders.", "folder": folder.path, "imported": 0])
        }
    }

    // MARK: Reading state

    func reload() {
        loadPlugins()
        guard connected, !reading else { return }
        reading = true
        let folder = bridge
        Task.detached {
            let decoder = JSONDecoder()
            let state = (try? Data(contentsOf: folder.appendingPathComponent("state.json"))).flatMap { try? decoder.decode(PipelineState.self, from: $0) }
            let overview = (try? Data(contentsOf: folder.appendingPathComponent("overview.json"))).flatMap { try? decoder.decode(Overview.self, from: $0) }
            let coverage = (try? Data(contentsOf: folder.appendingPathComponent("coverage.json"))).flatMap { try? decoder.decode(Coverage.self, from: $0) }
            var feedback: [String: Feedback] = [:]
            if let files = try? FileManager.default.contentsOfDirectory(at: folder.appendingPathComponent("Feedback"), includingPropertiesForKeys: nil) {
                for f in files where f.pathExtension == "json" {
                    if let d = try? Data(contentsOf: f), let fb = try? decoder.decode(Feedback.self, from: d) { feedback[fb.exercise_id] = fb }
                }
            }
            await MainActor.run {
                self.reading = false
                guard let state else { return }
                for e in state.events where !self.seenEvents.contains(e.id) {
                    if self.loadedOnce { self.notify(e.title, e.body) }
                    self.seenEvents.insert(e.id)
                }
                self.loadedOnce = true
                self.state = state
                if let overview { self.overview = overview }
                self.coverage = coverage
                self.autoSyncIfStale()
                self.feedback = feedback
                Companion.shared.observe()
                self.startWorkerIfNeeded()
                if let r = state.request, r.status == "processing", state.sources["canvas"]?.status == "collecting" {
                    self.canvas.check(root: self.workspace, ident: r.id)
                }
            }
        }
    }

    // MARK: Daily auto-sync

    static var todayString: String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "America/New_York")
        return f.string(from: Date())
    }
    var planIsToday: Bool { brief?.date == AppModel.todayString }

    /// Opening the app on a new day starts the sync on its own. One automatic try per day.
    private func autoSyncIfStale() {
        guard connected, !busy, !planIsToday else { return }
        let hour = Calendar.current.component(.hour, from: Date())
        guard hour >= 5 else { return }
        let key = "autoSyncDay"
        guard UserDefaults.standard.string(forKey: key) != AppModel.todayString else { return }
        UserDefaults.standard.set(AppModel.todayString, forKey: key)
        requestSync()
    }

    // MARK: Task status

    func status(_ t: StudyTask) -> TaskStatus {
        if grading.contains(t.exerciseID) { return .checking }
        guard let fb = feedback[t.exerciseID] else { return (drafts[t.exerciseID]?.isEmpty == false) ? .started : .open }
        if fb.correct { return .correct }
        if let r = fb.retry, feedback[r.exerciseID]?.correct == true { return .correct }
        return .missed
    }
    enum TaskStatus { case open, started, checking, missed, correct }

    var doneCount: Int { tasks.filter { status($0) == .correct }.count }
    var nextTask: StudyTask? { tasks.first { status($0) != .correct } }
    func isCorrect(_ exerciseID: String?) -> Bool {
        guard let id = exerciseID, let t = tasks.first(where: { $0.exerciseID == id }) else { return false }
        return status(t) == .correct
    }
    var remainingMinutes: Int { tasks.filter { status($0) != .correct }.reduce(0) { $0 + $1.minutes } }

    // MARK: Python bridge

    nonisolated static func python(_ script: String, _ args: [String], root: String, stdin: Data? = nil) async -> (Int32, Data) {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let p = Process()
                guard let python = GenesisRuntime.python else {
                    continuation.resume(returning: (-1, Data("Bundled Python runtime is missing.".utf8)))
                    return
                }
                p.executableURL = python
                p.arguments = [root + "/outputs/" + script] + args
                p.currentDirectoryURL = URL(fileURLWithPath: root + "/outputs")
                p.environment = GenesisRuntime.environment
                let out = Pipe(), inp = Pipe(), err = Pipe()
                p.standardOutput = out; p.standardError = err; p.standardInput = inp
                do {
                    try p.run()
                    if let stdin { inp.fileHandleForWriting.write(stdin) }
                    try? inp.fileHandleForWriting.close()
                    let data = out.fileHandleForReading.readDataToEndOfFile()
                    _ = err.fileHandleForReading.readDataToEndOfFile()
                    p.waitUntilExit()
                    continuation.resume(returning: (p.terminationStatus, data))
                } catch {
                    continuation.resume(returning: (-1, Data(error.localizedDescription.utf8)))
                }
            }
        }
    }

    func runScript(_ script: String, _ args: [String], stdin: Data? = nil, done: @escaping (Data?) -> Void) {
        let root = workspace
        Task {
            let (code, data) = await AppModel.python(script, args, root: root, stdin: stdin)
            done(code == 0 ? data : nil)
        }
    }

    // MARK: Sync

    func requestSync() {
        guard connected else { message = "Choose your Genesis folder in Settings first."; return }
        guard plugins.contains("canvas") else { message = "Add the Canvas plugin (Settings › Plugins) so Genesis can build your plan from your classes."; return }
        do {
            guard !(try GenesisConfiguration.load(root: workspace).courses).isEmpty else {
                message = "Add your classes in Settings > Accounts before syncing."; return
            }
        } catch { message = error.localizedDescription; return }
        guard !busy else { return }
        syncing = true; message = ""
        runScript("school_hq_app_bridge.py", ["request", "--policy", "local-first-v4"]) { data in
            self.syncing = false
            if data == nil { self.message = "Could not start the sync. Your plan is unchanged." }
            self.reload()
        }
    }

    func cancelSync() {
        guard let id = state?.request?.id else { return }
        runScript("school_hq_app_bridge.py", ["cancel", "--request-id", id, "--detail", "Cancelled from the app."]) { _ in self.reload() }
    }

    private func startWorkerIfNeeded() {
        guard connected, state?.request?.manual == true, ["queued", "processing"].contains(state?.request?.status ?? ""),
              runner?.isRunning != true, let ident = state?.request?.id, state?.request?.policy_id == "local-first-v4" else { return }
        let lockPath = bridge.appendingPathComponent(".local-worker.lock").path
        let fd = Darwin.open(lockPath, O_RDWR | O_CREAT, mode_t(0o600))
        guard fd >= 0 else { return }
        let free = flock(fd, LOCK_EX | LOCK_NB) == 0
        if free { _ = flock(fd, LOCK_UN) }
        _ = Darwin.close(fd)
        guard free else { return }
        let p = Process()
        guard let python = GenesisRuntime.python else { message = "Bundled Python runtime is missing."; return }
        p.executableURL = python
        p.environment = GenesisRuntime.environment
        p.arguments = [workspace + "/outputs/school_hq_local_worker.py", "--request-id", ident]
        let log = bridge.appendingPathComponent("worker.log")
        if !FileManager.default.fileExists(atPath: log.path) { FileManager.default.createFile(atPath: log.path, contents: nil, attributes: [.posixPermissions: 0o600]) }
        if let h = try? FileHandle(forWritingTo: log) { _ = try? h.seekToEnd(); p.standardOutput = h; p.standardError = h }
        runner = p
        do { try p.run() } catch { runner = nil; message = "The sync worker could not start: \(error.localizedDescription)" }
    }

    var syncFraction: Double? {
        guard busy else { return nil }
        if let p = state?.request?.progress { return p.fraction }
        return state?.request?.status == "queued" ? 0.01 : 0.03
    }
    var syncLabel: String {
        if state?.request?.status == "queued" { return "Starting…" }
        if state?.request?.progress?.step == "sources" || state?.request?.progress == nil, state?.sources["canvas"]?.status == "collecting" {
            return canvas.message.hasPrefix("Checking") || canvas.message.hasPrefix("Downloading") ? canvas.message : "Checking Canvas…"
        }
        return state?.request?.progress?.label ?? state?.request?.stage ?? "Syncing…"
    }
    var syncProblem: (text: String, action: SyncFix?)? {
        guard syncFailed, let detail = state?.request?.detail else { return nil }
        let lower = detail.lowercased()
        if lower.contains("canvas") && (lower.contains("sign-in") || lower.contains("sign in") || lower.contains("connect canvas") || lower.contains("login")) {
            return ("Canvas needs you to sign in again.", .canvas)
        }
        return (detail.count > 260 ? String(detail.prefix(260)) + "…" : detail, nil)
    }
    enum SyncFix { case canvas }

    // MARK: Drafts and grading

    func setDraft(_ id: String, _ text: String) {
        drafts[id] = text
        Companion.shared.noteActivity()
        UserDefaults.standard.set(drafts, forKey: "drafts")
    }

    func canSubmit(_ id: String) -> Bool {
        !(drafts[id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !(attachments[id] ?? []).isEmpty
    }

    func submit(_ task: StudyTask) {
        let id = task.exerciseID
        guard canSubmit(id), let briefID = brief?.id else { return }
        let answer = drafts[id] ?? ""
        grading.insert(id); gradeError[id] = nil; unreadable[id] = nil
        let payload: [String: Any] = ["brief_id": briefID, "exercise_id": id, "answer": answer, "attachments": attachments[id] ?? [],
                                      "used_help": usedHelp.contains(id), "attempt_id": UUID().uuidString]
        let data = try? JSONSerialization.data(withJSONObject: payload)
        runScript("school_hq_grader.py", ["submit"], stdin: data) { out in
            self.grading.remove(id)
            if let out, let obj = try? JSONSerialization.jsonObject(with: out) as? [String: Any], let u = obj["unreadable"] as? [String: Any] {
                // Not graded: nothing was recorded. Show what to fix and what clearer looks like.
                self.unreadable[id] = Unreadable(reason: u["reason"] as? String ?? "Part of the answer couldn't be read.",
                                                 tips: u["tips"] as? [String] ?? [], examples: u["examples"] as? [String] ?? [])
            } else if let out, let obj = try? JSONSerialization.jsonObject(with: out) as? [String: Any], let error = obj["error"] as? String {
                self.gradeError[id] = error
            } else if out == nil {
                self.gradeError[id] = "Checking failed. Your answer is saved; try again in a moment."
            } else {
                Companion.shared.graded(out, exerciseID: id)
            }
            self.reload()
        }
    }

    // MARK: Digital paper (drag-and-drop pages of written work)

    /// Saves dropped images or PDFs as PNG pages under Bridge/Evidence/uploads, so the
    /// grader can read them. PDFs become one image per page (up to 8 pages).
    func addPages(_ urls: [URL], to id: String) {
        let folder = bridge.appendingPathComponent("Evidence/uploads/" + String(id.replacingOccurrences(of: #"[^A-Za-z0-9_-]"#, with: "_", options: .regularExpression).suffix(60)))
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        var added: [String] = []
        for url in urls {
            for image in PageImages.images(from: url) {
                let dest = folder.appendingPathComponent(String(UUID().uuidString.prefix(8)) + ".png")
                if PageImages.writePNG(image, to: dest) { added.append(dest.path) }
            }
        }
        if added.isEmpty { gradeError[id] = "That file couldn't be opened as a page. Drop a PNG, JPEG, HEIC or PDF."; return }
        gradeError[id] = nil; unreadable[id] = nil
        Companion.shared.noteActivity()
        attachments[id, default: []] += added
        if attachments[id]!.count > 8 { attachments[id] = Array(attachments[id]!.suffix(8)) }
        UserDefaults.standard.set(attachments, forKey: "answerPages")
    }

    func removePage(_ path: String, from id: String) {
        attachments[id]?.removeAll { $0 == path }
        if attachments[id]?.isEmpty == true { attachments[id] = nil }
        UserDefaults.standard.set(attachments, forKey: "answerPages")
    }

    // MARK: Notes

    func refreshNotes() {
        runScript("school_hq_context.py", ["list"]) { data in
            if let data, let file = try? JSONDecoder().decode(NotesFile.self, from: data) { self.notes = file.notes }
        }
    }
    func addNote(_ text: String) {
        let data = try? JSONSerialization.data(withJSONObject: ["text": text])
        runScript("school_hq_context.py", ["add"], stdin: data) { _ in self.refreshNotes() }
    }
    func removeNote(_ id: String) {
        notes.removeAll { $0.id == id }
        runScript("school_hq_context.py", ["remove", "--id", id]) { _ in self.refreshNotes() }
    }

    // MARK: Library search

    func search(_ query: String) {
        guard query.trimmingCharacters(in: .whitespaces).count >= 2 else { searchHits = []; return }
        runScript("school_hq_local_store.py", ["search", query]) { data in
            if let data, let hits = try? JSONDecoder().decode([SearchHit].self, from: data) { self.searchHits = hits }
        }
    }

    // MARK: Workspace and alerts

    func chooseWorkspace() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.prompt = "Use this folder"
        panel.message = "Choose the Genesis project folder (the one that contains outputs)."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        scoped?.stopAccessingSecurityScopedResource(); scoped = url; _ = url.startAccessingSecurityScopedResource()
        workspace = url.path
        if let b = try? url.bookmarkData(options: .withSecurityScope, includingResourceValuesForKeys: nil, relativeTo: nil) { UserDefaults.standard.set(b, forKey: "schoolHQBookmark") }
        UserDefaults.standard.set(workspace, forKey: "schoolHQWorkspace")
        connected = GenesisRuntime.python != nil && FileManager.default.fileExists(atPath: workspace + "/outputs/school_hq_app_bridge.py")
        reload(); refreshNotes()
    }

    func notify(_ title: String, _ body: String) {
        guard UserDefaults.standard.bool(forKey: "notifications") else { return }
        let c = UNMutableNotificationContent(); c.title = title; c.body = body
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
    }

    func enableNotifications() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { granted, _ in
            Task { @MainActor in UserDefaults.standard.set(granted, forKey: "notifications") }
        }
    }

    /// End of the semester: the window becomes black with only the orb, until you come back.
    func setFarewell(_ on: Bool) {
        farewell = on
        UserDefaults.standard.set(on, forKey: "farewell")
        if on { UserDefaults.standard.set(false, forKey: "farewellSeen"); Companion.shared.dismiss() }
    }

    func setAppearance(_ value: String) {
        appearance = value
        UserDefaults.standard.set(value, forKey: "appearance")
        NSApp.appearance = value == "light" ? NSAppearance(named: .aqua) : value == "dark" ? NSAppearance(named: .darkAqua) : nil
    }
}

func shortDate(_ iso: String?) -> String {
    guard let iso else { return "Never" }
    let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let g = ISO8601DateFormatter()
    guard let d = f.date(from: iso) ?? g.date(from: iso) else { return iso }
    let out = DateFormatter(); out.timeZone = TimeZone(identifier: "America/New_York")
    out.dateFormat = Calendar.current.isDateInToday(d) ? "'today at' h:mm a" : "MMM d 'at' h:mm a"
    return out.string(from: d)
}

func dayLabel(_ isoDay: String, days: Int) -> String {
    if days == 0 { return "Today" }
    if days == 1 { return "Tomorrow" }
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
    guard let d = f.date(from: isoDay) else { return isoDay }
    let out = DateFormatter(); out.dateFormat = days < 7 ? "EEEE" : "MMM d"
    return out.string(from: d)
}
