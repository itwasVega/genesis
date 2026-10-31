import SwiftUI
import UniformTypeIdentifiers
import AppKit
import PDFKit

struct TaskView: View {
    @EnvironmentObject var model: AppModel
    var task: StudyTask
    @State private var showSource = true
    @State private var selectedSource: TaskSource?
    @State private var teachingOpen = true
    @State private var showHint = false
    @State private var showSolution = false

    var hasSources: Bool { task.sources?.contains { $0.localURL != nil } == true }
    var index: Int { (model.tasks.firstIndex { $0.exerciseID == task.exerciseID } ?? 0) + 1 }

    var body: some View {
        VStack(spacing: 0) {
            topBar
            Rectangle().fill(Theme.border).frame(height: 1)
            HStack(spacing: 0) {
                ScrollView {
                    content
                        .padding(.horizontal, 40).padding(.vertical, 30)
                        .frame(maxWidth: 760, alignment: .leading)
                        .frame(maxWidth: .infinity)
                }
                if showSource && hasSources {
                    Rectangle().fill(Theme.border).frame(width: 1)
                    SourcePane(sources: (task.sources ?? []).filter { $0.localURL != nil }, selected: $selectedSource)
                        .frame(minWidth: 340, idealWidth: 430, maxWidth: 560)
                        .transition(.move(edge: .trailing).combined(with: .opacity))
                }
            }
        }
        .animation(.spring(response: 0.38, dampingFraction: 0.88), value: showSource)
        .onAppear {
            teachingOpen = ["learn", "repair", "catch_up", "prep"].contains(task.mode ?? "") && model.feedback[task.exerciseID] == nil
            selectedSource = task.problemSource ?? task.readSources.first
        }
    }

    var topBar: some View {
        HStack(spacing: 10) {
            Button { model.openTask = nil } label: { HStack(spacing: 6) { GlyphView(glyph: .back, size: 10); Text("Today") } }
                .buttonStyle(QuietButtonStyle()).keyboardShortcut(.escape, modifiers: [])
            if task.parent == nil { Text("\(index) of \(model.tasks.count)").font(Typeface.sans(12)).foregroundStyle(Theme.tertiary) }
            Spacer()
            if hasSources {
                Button { showSource.toggle() } label: { HStack(spacing: 7) { GlyphView(glyph: .panel, size: 13); Text(showSource ? "Hide source" : "Show source") } }
                    .buttonStyle(QuietButtonStyle())
            }
            if let next = nextTask {
                Button { model.openTask = next } label: { HStack(spacing: 6) { Text("Next"); GlyphView(glyph: .forward, size: 10) } }
                    .buttonStyle(QuietButtonStyle())
            }
        }
        .padding(.horizontal, 18).padding(.vertical, 10)
        .padding(.top, 18)
    }

    var nextTask: StudyTask? {
        guard let i = model.tasks.firstIndex(where: { $0.exerciseID == task.exerciseID }) else { return nil }
        return model.tasks.dropFirst(i + 1).first { model.status($0) != .correct } ?? model.tasks.dropFirst(i + 1).first
    }

    @ViewBuilder var content: some View {
        VStack(alignment: .leading, spacing: 26) {
            // Header
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 6) {
                    Tag(text: Theme.courseLabel(task.courseID))
                    Tag(text: task.modeLabel)
                    Tag(text: minutesLabel(task.minutes))
                    if let o = task.originLabel { Text(o).font(Typeface.sans(11)).foregroundStyle(Theme.tertiary).padding(.leading, 4) }
                }
                InlineText(text: task.title, size: 24, singleLine: true, display: true)
                if task.mode == "mock" { ExamTimer(minutes: task.minutes) }
                if let why = task.reason {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("Why now").font(Typeface.sans(11, .medium)).foregroundStyle(Theme.tertiary)
                        InlineText(text: why, size: 13.5, color: Theme.secondary)
                    }
                }
            }

            // Teaching
            if let teach = task.teaching_blocks, !teach.isEmpty {
                VStack(alignment: .leading, spacing: 14) {
                    Button { withAnimation(.easeInOut(duration: 0.25)) { teachingOpen.toggle() } } label: {
                        HStack {
                            Text("Learn it first").font(Typeface.sans(14, .medium))
                            Spacer()
                            GlyphView(glyph: .forward, size: 9).rotationEffect(.degrees(90)).rotationEffect(.degrees(teachingOpen ? 0 : -90)).font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.tertiary)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    if teachingOpen {
                        Blocks(blocks: teach, size: 15)
                        if let ex = task.example_blocks, !ex.isEmpty {
                            SectionTitle(text: "Worked example")
                            Blocks(blocks: ex, size: 15)
                        }
                        ForEach(task.readSources) { s in sourceChip(s) }
                    }
                }
                .card(padding: 20, radius: 14)
            }

            // Steps
            if let steps = task.steps, !steps.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    SectionTitle(text: "Do this")
                    ForEach(Array(steps.enumerated()), id: \.offset) { i, step in
                        HStack(alignment: .firstTextBaseline, spacing: 12) {
                            Text("\(i + 1)").font(Typeface.mono(12, .medium)).foregroundStyle(Theme.tertiary).frame(width: 16, alignment: .trailing)
                            InlineText(text: stripNumber(step), size: 14)
                        }
                    }
                }
            }

            // Problem
            ProblemSection(task: task, title: task.problem_label ?? "Problem", onSource: { s in selectedSource = s; showSource = true })

            if let h = task.hint_blocks, !h.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    if showHint {
                        SectionTitle(text: "Hint")
                        Blocks(blocks: h, size: 14.5)
                    } else {
                        Button { showHint = true; model.usedHelp.insert(task.exerciseID) } label: { HStack(spacing: 7) { GlyphView(glyph: .hint, size: 12); Text("Show a hint") } }
                            .buttonStyle(QuietButtonStyle())
                    }
                }
                .transition(.opacity)
            }

            AnswerArea(task: task, showSolution: $showSolution)

            if let fb = model.feedback[task.exerciseID], let retry = fb.retry, !fb.correct {
                RetrySection(retry: retry)
            }

            if let cue = task.cue {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    GlyphView(glyph: .hint, size: 10).foregroundStyle(Theme.tertiary)
                    InlineText(text: cue, size: 13, color: Theme.secondary)
                }
            }
        }
    }

    func sourceChip(_ s: TaskSource) -> some View {
        Button { selectedSource = s; showSource = true } label: {
            HStack(spacing: 6) {
                GlyphView(glyph: .page, size: 11)
                Text(s.label + (s.pageLabel.map { Theme.sep + $0 } ?? "")).font(Typeface.mono(12, .medium))
            }
            .foregroundStyle(Theme.chipText)
            .padding(.horizontal, 9).padding(.vertical, 5)
            .background(Theme.chip, in: RoundedRectangle(cornerRadius: 7))
        }
        .buttonStyle(.plain)
    }

    func stripNumber(_ s: String) -> String {
        s.replacingOccurrences(of: #"^\s*\d+[.)]\s+"#, with: "", options: .regularExpression)
    }
}

struct ProblemSection: View {
    var task: StudyTask
    var title: String
    var onSource: (TaskSource) -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                SectionTitle(text: title)
                Spacer()
                if let s = task.problemSource {
                    Button { onSource(s) } label: {
                        Text(s.label + (s.pageLabel.map { Theme.sep + $0 } ?? "")).font(Typeface.mono(11.5, .medium)).foregroundStyle(Theme.chipText)
                            .padding(.horizontal, 8).padding(.vertical, 4).background(Theme.chip, in: RoundedRectangle(cornerRadius: 6))
                    }
                    .buttonStyle(.plain)
                    .help("Open the original page")
                }
            }
            Blocks(blocks: task.prompt_blocks ?? [PromptBlock(kind: "paragraph", text: task.question ?? "", language: nil)], size: 15.5)
            if task.aids != nil || task.done_when != nil {
                // Conditions and finish line: full text, one aligned row each, never cut off.
                VStack(alignment: .leading, spacing: 12) {
                    Rectangle().fill(Theme.borderStrong).frame(height: 1)
                    Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 16, verticalSpacing: 10) {
                        if let aids = task.aids { GridRow { meta("HOW"); detail(aids) } }
                        if let done = task.done_when { GridRow { meta("DONE WHEN"); detail(done) } }
                    }
                }
                .padding(.top, 2)
            }
        }
        .card(padding: 22, radius: 16)
    }

    func meta(_ t: String) -> some View {
        Text(t).font(Typeface.label(9.5)).tracking(1).foregroundStyle(Theme.tertiary).fixedSize().gridColumnAlignment(.leading)
    }
    func detail(_ t: String) -> some View {
        InlineText(text: t, size: 12.5, color: Theme.secondary).fixedSize(horizontal: false, vertical: true).frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct AnswerArea: View {
    @EnvironmentObject var model: AppModel
    var task: StudyTask
    @Binding var showSolution: Bool

    var draft: Binding<String> {
        Binding(get: { model.drafts[task.exerciseID] ?? "" }, set: { model.setDraft(task.exerciseID, $0) })
    }

    @State private var dropTargeted = false

    var body: some View {
        let id = task.exerciseID
        let fb = model.feedback[id]
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                SectionTitle(text: "Your answer")
                Spacer()
                if !(model.drafts[id] ?? "").isEmpty || model.attachments[id] != nil { Text("Saved").font(Typeface.sans(11)).foregroundStyle(Theme.tertiary).transition(.opacity) }
            }
            // One box: type, drop a file, or attach your notes; checking happens from the box too.
            AnswerComposer(task: task, text: draft)
            Text(task.answer_format ?? AnswerGuide.text(task.answer_type ?? "short_answer"))
                .font(Typeface.sans(12)).foregroundStyle(Theme.tertiary).fixedSize(horizontal: false, vertical: true)
            if model.grading.contains(id) {
                HStack(spacing: 14) {
                    ScribbleLoader().frame(width: 44, height: 18)
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Checking your answer against the rubric…").font(Typeface.sans(13, .medium)).shimmer()
                        ProgressLine(value: nil, height: 3).frame(maxWidth: 260)
                    }
                }
                .padding(.vertical, 6)
                .transition(.opacity)
            } else {
                if model.usedHelp.contains(id) { Text("Hint used — counts as practice with help").font(Typeface.sans(11)).foregroundStyle(Theme.tertiary) }
            }
            if let err = model.gradeError[id] { Text(err).font(Typeface.sans(13)).foregroundStyle(Theme.error) }
            if let u = model.unreadable[id], !model.grading.contains(id) {
                UnreadableCard(info: u).transition(.move(edge: .bottom).combined(with: .opacity))
            }
            if let latest = fb?.latest, !model.grading.contains(id) {
                FeedbackCard(attempt: latest, workedSolution: fb?.worked_solution, showSolution: $showSolution, onReveal: { model.usedHelp.insert(id) },
                             onNext: latest.outcome == "correct" ? { model.openTask = model.nextTask } : nil)
                    .id(latest.attempt_id)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: model.grading.contains(id))
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: fb?.latest?.attempt_id)

    }
}

/// How to write the answer so it can be read and graded; shown under every answer box.
enum AnswerGuide {
    static func text(_ type: String) -> String {
        switch type {
        case "derivation": return "One step per line, typed the way you'd write it (x^2, sqrt(x), 3/(x+1), 233 = 1·144 + 89). Or drop a photo or PDF of your paper on the box."
        case "proof": return "One claim per line, each with its reason. Or drop a photo or PDF of your written proof."
        case "memory_trace", "code_trace": return "One change per line, e.g. line 4: x = 5, p → node A. A photo of a hand-drawn trace works too."
        case "table": return "One row per line with columns separated by |. Or drop a photo of your table."
        case "numeric": return "Just the number or an exact fraction, like 7 or -3/4."
        case "code": return "Type or paste your code. A clear photo of handwritten code also works."
        case "multiple_choice": return "The letter or the exact choice text is enough."
        default: return "Type your answer, or drop a photo or PDF of your paper."
        }
    }
}

/// Attach photos, screenshots or PDFs of written work (dragging onto the box works too).
struct AttachButton: View {
    @EnvironmentObject var model: AppModel
    var id: String
    var body: some View {
        Button { pick() } label: {
            HStack(spacing: 7) { GlyphView(glyph: .page, size: 11); Text(model.attachments[id] == nil ? "Attach your paper" : "Add a page") }.fixedSize()
        }
        .buttonStyle(QuietButtonStyle())
        .help("Attach a photo, screenshot or PDF of your written work — or drag it onto the answer box")
    }
    func pick() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image, .pdf]; panel.allowsMultipleSelection = true; panel.canChooseDirectories = false
        panel.message = "Choose photos, screenshots or PDFs of your work"
        if panel.runModal() == .OK { model.addPages(panel.urls, to: id) }
    }
}

/// Thumbnails of attached pages; click to open, × to remove.
struct PagesRow: View {
    @EnvironmentObject var model: AppModel
    var id: String
    var body: some View {
        if let pages = model.attachments[id], !pages.isEmpty {
        HStack(alignment: .center, spacing: 12) {
            ForEach(pages, id: \.self) { path in
                Button { NSWorkspace.shared.open(URL(fileURLWithPath: path)) } label: {
                    Group {
                        if let img = NSImage(contentsOfFile: path) { Image(nsImage: img).resizable().scaledToFill() } else { Theme.well }
                    }
                    .frame(width: 64, height: 84).clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).strokeBorder(Theme.ring, lineWidth: 1))
                }
                .buttonStyle(.plain).help("Open this page")
                .overlay(alignment: .topTrailing) {
                    Button { model.removePage(path, from: id) } label: {
                        GlyphView(glyph: .close, size: 7).foregroundStyle(.white).frame(width: 18, height: 18).background(Color.black.opacity(0.72), in: Circle())
                    }
                    .buttonStyle(.plain).padding(4).help("Remove this page")
                }
            }
            Text(pages.count == 1 ? "1 page attached" : "\(pages.count) pages attached").font(Typeface.sans(12)).foregroundStyle(Theme.tertiary)
            Spacer(minLength: 0)
        }
        .padding(.top, 6)
        }
    }
}

/// Accepts dropped files, or raw image data dragged out of a notes app.
enum PageDrop {
    static func load(_ providers: [NSItemProvider], done: @escaping ([URL]) -> Void) {
        let group = DispatchGroup(); var urls: [URL] = []; let lock = NSLock()
        for p in providers {
            group.enter()
            if p.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
                _ = p.loadDataRepresentation(forTypeIdentifier: UTType.fileURL.identifier) { data, _ in
                    if let data, let url = URL(dataRepresentation: data, relativeTo: nil) { lock.lock(); urls.append(url); lock.unlock() }
                    group.leave()
                }
            } else {
                let type = p.hasItemConformingToTypeIdentifier(UTType.pdf.identifier) ? UTType.pdf : UTType.image
                _ = p.loadDataRepresentation(forTypeIdentifier: type.identifier) { data, _ in
                    if let data {
                        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + (type == .pdf ? ".pdf" : ".png"))
                        if (try? data.write(to: url)) != nil { lock.lock(); urls.append(url); lock.unlock() }
                    }
                    group.leave()
                }
            }
        }
        group.notify(queue: .main) { done(urls) }
    }
}

/// Shown instead of a grade when the answer can't be read with confidence. Nothing is recorded.
struct UnreadableCard: View {
    var info: Unreadable
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                GlyphView(glyph: .hint, size: 13).foregroundStyle(Theme.focus)
                Text("I couldn't read this clearly enough to grade it").font(Typeface.headline(15)).lineLimit(1)
            }
            InlineText(text: info.reason, size: 14, color: Theme.secondary)
            Text("Nothing was recorded and nothing counts against you. Your typed answer and pages are kept: fix just the unclear part and check again.").font(Typeface.sans(12)).foregroundStyle(Theme.tertiary)
            if !info.examples.isEmpty {
                Text("CLEARER LOOKS LIKE").font(Typeface.label(9.5)).tracking(1).foregroundStyle(Theme.tertiary).padding(.top, 2)
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(info.examples, id: \.self) { Text($0).font(Typeface.mono(13)).foregroundStyle(Theme.ink).textSelection(.enabled) }
                }
                .padding(12).frame(maxWidth: .infinity, alignment: .leading)
                .background(Theme.well, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            if !info.tips.isEmpty {
                VStack(alignment: .leading, spacing: 5) {
                    ForEach(info.tips, id: \.self) { tip in
                        HStack(alignment: .firstTextBaseline, spacing: 8) { Text("·").foregroundStyle(Theme.tertiary); InlineText(text: tip, size: 13, color: Theme.secondary) }
                    }
                }
            }
        }
        .padding(18)
        .background(Theme.focus.opacity(0.06), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Theme.focus.opacity(0.25), lineWidth: 1))
    }
}

struct FeedbackCard: View {
    var attempt: Attempt
    var workedSolution: String?
    @Binding var showSolution: Bool
    var onReveal: () -> Void
    var onNext: (() -> Void)? = nil

    var correct: Bool { attempt.outcome == "correct" }
    var title: String {
        switch attempt.outcome {
        case "correct": return "Correct"
        case "partially_correct": return "Almost — one thing to fix"
        case "unreadable": return "Couldn't read that answer"
        default: return "Not yet"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                Group {
                    if correct { DrawOn(shape: SketchCheck(), color: Theme.success, lineWidth: 2.6, duration: 0.5) }
                    else { DrawOn(shape: SketchCross(), color: Theme.error, lineWidth: 2.4, duration: 0.45) }
                }
                .frame(width: 24, height: 24)
                Text(title).font(Typeface.headline(15)).lineLimit(1).foregroundStyle(correct ? Theme.success : Theme.ink)
                Spacer()
                if let s = attempt.score, !correct { Text("\(Int(s * 100))%").font(Typeface.mono(12)).foregroundStyle(Theme.tertiary) }
            }
            InlineText(text: attempt.feedback, size: 14.5)
            if let m = attempt.misconception, !correct {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("The idea to fix").font(Typeface.sans(11, .medium)).foregroundStyle(Theme.tertiary)
                    InlineText(text: m, size: 14, color: Theme.secondary)
                }
            }
            if let n = attempt.next_step, !correct { InlineText(text: "**Next:** " + n, size: 14, color: Theme.secondary) }
            if correct, let onNext {
                Button(action: onNext) { HStack(spacing: 8) { Text("Next task"); GlyphView(glyph: .arrow, size: 11) } }
                    .primaryAction().padding(.top, 4)
            }
            if !correct, let sol = workedSolution, !sol.isEmpty {
                if showSolution {
                    SectionTitle(text: "Worked solution")
                    if sol.contains("```") || sol.contains("{") && sol.contains(";") {
                        CodeBlock(code: sol.replacingOccurrences(of: "```", with: ""), language: "")
                    } else {
                        Blocks(blocks: [PromptBlock(kind: "paragraph", text: sol, language: nil)], size: 15)
                    }
                } else {
                    Button("Show the worked solution") { showSolution = true; onReveal() }.buttonStyle(QuietButtonStyle())
                }
            }
        }
        .padding(18)
        .background((correct ? Theme.success : Theme.error).opacity(0.07), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder((correct ? Theme.success : Theme.error).opacity(0.25), lineWidth: 1))
    }
}

struct RetrySection: View {
    @EnvironmentObject var model: AppModel
    var retry: StudyTask
    @State private var showSolution = false
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                Rectangle().fill(Theme.borderStrong).frame(width: 24, height: 1)
                Text("A different one, same idea").font(Typeface.headline(15)).lineLimit(1)
            }
            InlineText(text: retry.title, size: 17, color: Theme.secondary, singleLine: true, display: true)
            ProblemSection(task: retry, title: "Retry", onSource: { _ in })
            AnswerArea(task: retry, showSolution: $showSolution)
        }
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}

// MARK: - Source pane (PDF opened at the exact page, problem highlighted)

struct SourcePane: View {
    var sources: [TaskSource]
    @Binding var selected: TaskSource?

    var body: some View {
        VStack(spacing: 0) {
            if sources.count > 1 {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(sources) { s in
                            Button { selected = s } label: {
                                Text(s.label + (s.pageLabel.map { Theme.sep + $0 } ?? ""))
                                    .font(Typeface.sans(12, selected?.id == s.id ? .medium : .regular))
                                    .foregroundStyle(selected?.id == s.id ? Theme.ink : Theme.secondary)
                                    .padding(.horizontal, 10).padding(.vertical, 6)
                                    .background(selected?.id == s.id ? Theme.sand : .clear, in: Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(10)
                }
                Rectangle().fill(Theme.border).frame(height: 1)
            }
            if let s = selected ?? sources.first, let url = s.localURL {
                if s.isPDF {
                    PDFPane(url: url, page: s.pages?.first ?? 1, search: s.search).id(s.id)
                } else {
                    let doc = ReadableSource.load(url)
                    ScrollView {
                        Text(doc.text)
                            .font(doc.prose ? Typeface.sans(14) : Typeface.mono(12.5)).lineSpacing(doc.prose ? 4 : 0)
                            .textSelection(.enabled).padding(18)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                HStack {
                    Text(s.label).font(Typeface.sans(11)).foregroundStyle(Theme.tertiary).lineLimit(1)
                    Spacer()
                    Button("Open") { NSWorkspace.shared.open(url) }.buttonStyle(QuietButtonStyle())
                }
                .padding(.horizontal, 12).padding(.vertical, 6)
                .background(Theme.surface)
            }
        }
        .background(Theme.surface)
    }
}

/// What a saved source file says, in words: a Canvas assignment saved as data shows its
/// name, due date and instructions, never the raw JSON around them.
enum ReadableSource {
    static func load(_ url: URL) -> (text: String, prose: Bool) {
        guard let raw = try? String(contentsOf: url, encoding: .utf8) else { return ("This file can't be previewed.", true) }
        let ext = url.pathExtension.lowercased()
        if ext == "json", let obj = try? JSONSerialization.jsonObject(with: Data(raw.utf8)) as? [String: Any] {
            let a = obj["assignment"] as? [String: Any] ?? obj
            let name = a["name"] as? String ?? obj["title"] as? String
            let html = a["description"] as? String ?? obj["body"] as? String ?? obj["message"] as? String
            if name != nil || html != nil {
                var out = name.map { $0 + "\n" } ?? ""
                if let due = a["due_at"] as? String, let d = ISO8601DateFormatter().date(from: due) {
                    out += "Due " + d.formatted(.dateTime.weekday(.wide).month(.wide).day().hour().minute()) + "\n"
                }
                out += "\n" + plain(html ?? "")
                return (out.trimmingCharacters(in: .whitespacesAndNewlines), true)
            }
        }
        return (String(raw.prefix(60000)), ext == "txt" || ext == "md")
    }

    /// Canvas HTML to readable text: paragraphs and list items on their own lines, tags removed.
    static func plain(_ html: String) -> String {
        var t = html
        for (pattern, rep) in [("(?i)<br\\s*/?>", "\n"), ("(?i)</p>|</h\\d>|</div>", "\n\n"), ("(?i)<li[^>]*>", "\n• "), ("<[^>]+>", "")] {
            t = t.replacingOccurrences(of: pattern, with: rep, options: .regularExpression)
        }
        for (e, c) in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", "\""), ("&#39;", "'")] { t = t.replacingOccurrences(of: e, with: c) }
        t = t.replacingOccurrences(of: "[ \t]+", with: " ", options: .regularExpression)
        return t.replacingOccurrences(of: "\n\\s*\n\\s*\n+", with: "\n\n", options: .regularExpression)
    }
}

struct PDFPane: NSViewRepresentable {
    var url: URL
    var page: Int
    var search: String?

    func makeNSView(context: Context) -> PDFView {
        let v = PDFView()
        v.autoScales = true
        v.displayMode = .singlePageContinuous
        v.backgroundColor = .clear
        v.pageShadowsEnabled = true
        load(v)
        return v
    }

    func updateNSView(_ v: PDFView, context: Context) {}

    private func load(_ v: PDFView) {
        guard let doc = PDFDocument(url: url) else { return }
        v.document = doc
        let index = max(0, min(doc.pageCount - 1, page - 1))
        guard let target = doc.page(at: index) else { return }
        v.go(to: target)
        guard let search, !search.isEmpty else { return }
        // Highlight the problem: try the full anchor, then its first words.
        let words = search.split(separator: " ").map(String.init)
        var candidates = [search]
        if words.count > 6 { candidates.append(words.prefix(6).joined(separator: " ")) }
        if words.count > 3 { candidates.append(words.prefix(3).joined(separator: " ")) }
        for c in candidates {
            let hits = doc.findString(c, withOptions: [.caseInsensitive]).filter { $0.pages.contains(target) }
            if let hit = hits.first {
                hit.color = NSColor(hex: 0xE8D9A0, alpha: 0.55)
                v.highlightedSelections = [hit]
                v.go(to: hit)
                break
            }
        }
    }
}

/// Count-up timer for timed exam sets: start when you start, pause if you must.
struct ExamTimer: View {
    var minutes: Int
    @State private var start: Date?
    @State private var banked: TimeInterval = 0
    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { ctx in
            let elapsed = banked + (start.map { ctx.date.timeIntervalSince($0) } ?? 0)
            let over = elapsed > Double(minutes * 60)
            HStack(spacing: 12) {
                GlyphView(glyph: .clock, size: 13)
                Text(String(format: "%d:%02d", Int(elapsed) / 60, Int(elapsed) % 60))
                    .font(Typeface.mono(15, .medium)).monospacedDigit()
                    .foregroundStyle(over ? Theme.error : Theme.ink)
                    .contentTransition(.numericText())
                Text("of \(minutes) min, exam conditions").font(Typeface.sans(12)).foregroundStyle(Theme.tertiary)
                Spacer()
                Button(start == nil ? (banked == 0 ? "Start timer" : "Resume") : "Pause") {
                    if let s = start { banked += Date().timeIntervalSince(s); start = nil } else { start = Date() }
                }
                .secondaryAction()
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Theme.border, lineWidth: 1))
        }
    }
}
