import SwiftUI

struct TodayView: View {
    @EnvironmentObject var model: AppModel
    @State private var note = ""

    /// One word for the state of the day — Genesis is about beginnings, so the title says
    /// where you are in today's: Start here. → Begin. → Continue. → Caught up.
    var headline: String {
        if !model.connected || model.brief == nil || !model.planIsToday || model.tasks.isEmpty { return "Start here." }
        if model.doneCount == 0 { return "Begin." }
        if model.doneCount < model.tasks.count { return "Continue." }
        return "Caught up."
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                header
                if !model.connected {
                    EmptyPlan(title: "Connect your Genesis folder", detail: "Choose the project folder once in Settings.", showSync: false)
                } else if model.busy && (model.brief == nil || model.state?.request?.progress != nil) {
                    SyncPanel()
                }
                if model.brief != nil && !model.planIsToday && !model.busy {
                    HStack(spacing: 12) {
                        GlyphView(glyph: .calendar, size: 13).foregroundStyle(Theme.secondary)
                        Text(staleLabel).font(Typeface.sans(13))
                        Spacer()
                        Button("Sync now") { model.requestSync() }.primaryAction()
                    }
                    .card(padding: 14, radius: 14)
                }
                if let next = model.nextTask {
                    NextUpCard(task: next)
                } else if model.brief != nil && !model.tasks.isEmpty {
                    AllDoneCard()
                } else if model.connected && !model.busy {
                    EmptyPlan(title: "Nothing to begin yet", detail: "Sync and Genesis generates today's plan from what's actually on your courses.", showSync: true)
                }
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: 28) {
                        planList.frame(minWidth: 460)
                        sideColumn.frame(width: 300)
                    }
                    VStack(alignment: .leading, spacing: 28) { planList; sideColumn }
                }
            }
            .padding(.horizontal, 44).padding(.top, 40).padding(.bottom, 60)
            .frame(maxWidth: 1060, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
    }

    var staleLabel: String {
        guard let d = model.brief?.date, let date = ISO8601DateFormatter.day.date(from: d) else { return "This plan is from an earlier day. Sync to generate today's." }
        if Calendar.current.isDateInYesterday(date) { return "Yesterday's plan. Sync to generate today's." }
        return "Plan from " + date.formatted(.dateTime.month(.abbreviated).day()) + ". Sync to generate today's."
    }

    var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(Date.now.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day()).uppercased().replacingOccurrences(of: ",", with: ""))
                .font(Typeface.label(10.5)).tracking(1.4).foregroundStyle(Theme.tertiary)
            Text(headline).font(Typeface.largeTitle()).lineLimit(1).minimumScaleFactor(0.8)
                .contentTransition(.opacity).animation(.easeOut(duration: 0.3), value: headline)
            if !model.tasks.isEmpty && model.planIsToday {
                HStack(spacing: 14) {
                    Text(model.doneCount == model.tasks.count ? "All \(model.tasks.count) done. Tomorrow starts fresh." : "\(model.tasks.count - model.doneCount) to go\(Theme.sep)about \(minutesLabel(model.remainingMinutes))")
                        .font(Typeface.sans(13.5)).foregroundStyle(Theme.secondary)
                    ProgressLine(value: Double(model.doneCount) / Double(max(1, model.tasks.count)))
                        .frame(width: 140)
                }
            }
        }
    }

    var planList: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !model.tasks.isEmpty {
                HStack {
                    SectionTitle(text: "Plan")
                    Spacer()
                    if let b = model.brief { Text("Built " + shortDate(b.generated_at)).font(Typeface.sans(11)).foregroundStyle(Theme.tertiary) }
                }
                VStack(spacing: 0) {
                    ForEach(model.tasks) { task in
                        TaskRow(task: task)
                        if task.id != model.tasks.last?.id { Rectangle().fill(Theme.border).frame(height: 1).padding(.leading, 52) }
                    }
                }
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Theme.border, lineWidth: 1))
            }
        }
    }

    var sideColumn: some View {
        VStack(alignment: .leading, spacing: 26) {
            if let cov = model.coverage, cov.day == model.brief?.date, !cov.obligations.isEmpty || !(cov.undated ?? []).isEmpty {
                CoveragePanel(coverage: cov)
            } else if let up = model.overview?.upcoming, !up.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    SectionTitle(text: "Coming up")
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(up.prefix(6), id: \.self) { e in
                            HStack(alignment: .firstTextBaseline, spacing: 10) {
                                Text(dayLabel(e.date, days: e.days))
                                    .font(Typeface.sans(12, .medium)).foregroundStyle(e.days <= 1 ? Theme.ink : Theme.secondary)
                                    .frame(width: 74, alignment: .leading)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(e.name).font(Typeface.sans(13)).lineLimit(2)
                                    Text(Theme.courseLabel(e.course ?? "") + (e.exam ? Theme.sep + "exam" : "")).font(Typeface.sans(11)).foregroundStyle(Theme.tertiary)
                                }
                            }
                        }
                    }
                    .card(padding: 16, radius: 14)
                }
            }
            VStack(alignment: .leading, spacing: 10) {
                SectionTitle(text: "Tell Genesis")
                PillField(text: $note, placeholder: "Missed a class? Stuck on something?") {
                    let t = note.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !t.isEmpty else { return }
                    model.addNote(t); note = ""
                }
                Text("Used in your next sync. Your notes, not verified course facts.")
                    .font(Typeface.sans(11)).foregroundStyle(Theme.tertiary)
                PhoneNudge()
                FlowChips(notes: model.notes)
            }
        }
    }
}

/// "What this plan prepares you for": every upcoming test and assignment, topic by topic,
/// with what today does about each one, and why the rest waits.
struct CoveragePanel: View {
    @EnvironmentObject var model: AppModel
    var coverage: Coverage
    var items: [CoverageItem] { coverage.obligations }

    func label(_ t: CoverageTopic) -> String? {
        switch t.plan {
        case "shared": return "shared"
        case "covered": return t.state == "retained" ? "solid" : "done before"
        case "later": return "later"
        case "deferred": return "next"
        case "not_written": return "couldn't be written"
        default: return t.exercise_id == nil ? "later" : nil
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionTitle(text: "What's coming")
            VStack(alignment: .leading, spacing: 16) {
                ForEach(items) { item in
                    let done = item.topics.filter { model.isCorrect($0.exercise_id) }.count
                    let planned = item.topics.filter { $0.exercise_id != nil }.count
                    VStack(alignment: .leading, spacing: 7) {
                        HStack(alignment: .firstTextBaseline) {
                            Text(Theme.courseLabel(item.course) + Theme.sep + item.name)
                                .font(Typeface.sans(13, .medium)).lineLimit(2)
                            Spacer(minLength: 6)
                            Text(dayLabel(item.date, days: item.days))
                                .font(Typeface.sans(11, item.days <= 1 ? .semibold : .regular))
                                .foregroundStyle(item.days <= 1 ? Theme.ink : Theme.tertiary)
                        }
                        if item.certainty == "reported" {
                            Text("Date from your note, not confirmed by Canvas").font(Typeface.sans(11)).foregroundStyle(Theme.tertiary).fixedSize(horizontal: false, vertical: true)
                        }
                        if item.scope == "inferred" && item.kind == "test" {
                            Text("Topics inferred from recent lectures; no published scope").font(Typeface.sans(11)).foregroundStyle(Theme.tertiary).fixedSize(horizontal: false, vertical: true)
                        }
                        ForEach(item.topics, id: \.self) { t in
                            HStack(spacing: 7) {
                                Group {
                                    if model.isCorrect(t.exercise_id) || t.plan == "covered" {
                                        DrawOn(shape: SketchCheck(), color: t.plan == "covered" ? Theme.tertiary : Theme.success, lineWidth: 1.8, duration: 0.35)
                                    } else if t.exercise_id != nil {
                                        Circle().strokeBorder(Theme.ring, lineWidth: 1.2)
                                    } else {
                                        Circle().strokeBorder(Theme.ring.opacity(0.5), style: StrokeStyle(lineWidth: 1, dash: [2, 2]))
                                    }
                                }
                                .frame(width: 11, height: 11)
                                Text(t.title).font(Typeface.sans(12.5)).foregroundStyle(t.exercise_id == nil ? Theme.tertiary : Theme.secondary).lineLimit(1).layoutPriority(1)
                                if let l = label(t) { Text(l).font(Typeface.sans(10.5)).foregroundStyle(Theme.tertiary).lineLimit(1) }
                            }
                            .help(t.reason ?? "")
                        }
                        if planned > 0 {
                            ProgressLine(value: Double(done) / Double(planned), height: 3).padding(.top, 2)
                        } else if item.topics.isEmpty {
                            Text("No study material found for this yet.").font(Typeface.sans(11.5)).foregroundStyle(Theme.tertiary)
                        }
                    }
                }
                if let undated = coverage.undated, !undated.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("NO DATE FOUND").font(Typeface.label(9.5)).tracking(1).foregroundStyle(Theme.tertiary)
                        ForEach(undated, id: \.self) { u in
                            Text(Theme.courseLabel(u.course) + Theme.sep + u.name).font(Typeface.sans(12.5)).foregroundStyle(Theme.secondary).lineLimit(1)
                        }
                        Text("Tell Genesis the date (\"Calc test 3 is Nov 12\") to start preparing for it.").font(Typeface.sans(11)).foregroundStyle(Theme.tertiary).fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .card(padding: 16, radius: 14)
            let open = items.flatMap { $0.topics }.filter { ["later", "deferred", "not_written"].contains($0.plan ?? "") }.count
            if let all = Optional(items.flatMap { $0.topics }.filter { $0.exercise_id != nil }), !all.isEmpty, all.allSatisfy({ model.isCorrect($0.exercise_id) }) {
                HStack(spacing: 8) {
                    DrawOn(shape: SketchCheck(), color: Theme.success, lineWidth: 2).frame(width: 14, height: 14)
                    Text(open == 0 ? "Everything planned for what's coming is checked correct." : "Today's part is done. \(open) topic\(open == 1 ? "" : "s") still to come before these dates.")
                        .font(Typeface.sans(12.5, .medium))
                }
            }
        }
    }
}

struct FlowChips: View {
    @EnvironmentObject var model: AppModel
    var notes: [ContextNote]
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(notes) { n in
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 6) {
                        ForEach(n.chips, id: \.self) { c in Tag(text: c.label) }
                        Spacer()
                        if n.source == "iphone" { Text("FROM IPHONE").font(Typeface.label(9)).tracking(1).foregroundStyle(Theme.tertiary) }
                        Button { model.removeNote(n.id) } label: { GlyphView(glyph: .close, size: 8) }
                            .buttonStyle(QuietButtonStyle()).help("Remove note")
                    }
                    Text(n.text).font(Typeface.sans(12)).foregroundStyle(Theme.secondary).lineLimit(3)
                    if let e = n.effect { Text(e).font(Typeface.sans(11)).foregroundStyle(Theme.tertiary).fixedSize(horizontal: false, vertical: true) }
                }
                .padding(12)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Theme.border, lineWidth: 1))
                .transition(.scale(scale: 0.96).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.8), value: notes.map(\.id))
    }
}

struct TaskRow: View {
    @EnvironmentObject var model: AppModel
    var task: StudyTask
    @State private var hover = false

    var body: some View {
        let status = model.status(task)
        Button {
            model.openTask = task
        } label: {
            HStack(alignment: .top, spacing: 12) {
                StatusMark(status: status, number: task.number, isNext: model.nextTask?.exerciseID == task.exerciseID)
                    .frame(width: 14, height: 14).padding(.top, 3)
                VStack(alignment: .leading, spacing: 5) {
                    InlineText(text: task.title, size: 14, color: status == .correct ? Theme.tertiary : Theme.ink, singleLine: true)
                        .multilineTextAlignment(.leading)
                    HStack(spacing: 6) {
                        Text(Theme.courseLabel(task.courseID)).font(Typeface.sans(12, .medium)).foregroundStyle(Theme.secondary)
                        SeparatorMark()
                        Text(task.modeLabel).font(Typeface.sans(12)).foregroundStyle(Theme.tertiary)
                        SeparatorMark()
                        Text(minutesLabel(task.minutes)).font(Typeface.sans(12)).foregroundStyle(Theme.tertiary)
                        if status == .checking { Text("Checking…").font(Typeface.sans(12, .medium)).shimmer() }
                    }
                }
                Spacer(minLength: 8)
                GlyphView(glyph: .forward, size: 10).foregroundStyle(Theme.tertiary).opacity(hover ? 1 : 0).padding(.top, 4)
            }
            .padding(.horizontal, 16).padding(.vertical, 14)
            .background(hover ? Theme.sand.opacity(0.45) : .clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .animation(.easeOut(duration: 0.12), value: hover)
    }
}

/// Row status without numbers: a small ring that fills in as the task progresses.
struct StatusMark: View {
    var status: AppModel.TaskStatus
    var number: Int
    var isNext = false
    var body: some View {
        ZStack {
            switch status {
            case .correct:
                GlyphView(glyph: .check, size: 11).foregroundStyle(Theme.success)
            case .missed:
                Circle().strokeBorder(Theme.error.opacity(0.8), lineWidth: 1.2).frame(width: 9, height: 9)
            case .checking:
                ScribbleLoader().frame(width: 12, height: 12)
            case .started:
                Circle().trim(from: 0, to: 0.5).stroke(Theme.ink.opacity(0.7), lineWidth: 1.2).rotationEffect(.degrees(-90)).frame(width: 9, height: 9)
                Circle().strokeBorder(Theme.ring, lineWidth: 1.2).frame(width: 9, height: 9)
            case .open:
                if isNext {
                    Circle().strokeBorder(AngularGradient(colors: Theme.prismColors + [Theme.prismColors[0]], center: .center), lineWidth: 1.4).frame(width: 9, height: 9)
                } else {
                    Circle().strokeBorder(Theme.ring, lineWidth: 1.2).frame(width: 9, height: 9)
                }
            }
        }
        .accessibilityLabel(Text("\(status)"))
    }
}

struct NextUpCard: View {
    @EnvironmentObject var model: AppModel
    var task: StudyTask
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                SectionTitle(text: "Next up")
                Spacer()
                Tag(text: Theme.courseLabel(task.courseID))
                Tag(text: task.modeLabel)
                Tag(text: minutesLabel(task.minutes))
            }
            if let urgent = model.coverage?.obligations.first(where: { $0.days <= 1 && $0.topics.contains { $0.exercise_id != nil } }) {
                HStack(spacing: 6) {
                    GlyphView(glyph: .clock, size: 11)
                    Text(Theme.courseLabel(urgent.course) + " " + urgent.name + " is " + (urgent.days == 0 ? "today" : "tomorrow") + " — the first tasks get you ready")
                        .font(Typeface.sans(12.5, .medium))
                }
                .foregroundStyle(Theme.ink)
            }
            InlineText(text: task.title, size: 22, singleLine: true, display: true)
            if let why = task.reason { InlineText(text: why, size: 13.5, color: Theme.secondary) }
            HStack(spacing: 12) {
                Button { model.openTask = task } label: {
                    HStack(spacing: 8) { Text(model.status(task) == .open ? "Start" : "Continue"); GlyphView(glyph: .arrow, size: 11) }
                }
                .primaryAction()
                if let src = task.problemSource {
                    Text(src.label + (src.pageLabel.map { Theme.sep + $0 } ?? ""))
                        .font(Typeface.mono(12, .medium)).foregroundStyle(Theme.chipText)
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(Theme.chip, in: RoundedRectangle(cornerRadius: 6))
                }
            }
        }
        .card(padding: 24, radius: 18)
    }
}

struct AllDoneCard: View {
    @EnvironmentObject var model: AppModel
    /// What comes next: deferred work first, then topics paced for later days.
    var next: [String] {
        guard let cov = model.coverage, cov.day == model.brief?.date else { return [] }
        let deferred = (cov.deferred ?? []).map { Theme.courseLabel($0.course) + Theme.sep + $0.title }
        let later = cov.obligations.flatMap { ob in ob.topics.filter { $0.plan == "later" }.map { Theme.courseLabel(ob.course) + Theme.sep + $0.title } }
        var seen = Set<String>()
        return (deferred + later).filter { seen.insert($0).inserted }
    }
    var body: some View {
        HStack(alignment: .top, spacing: 20) {
            DrawOn(shape: SketchCheck(), color: Theme.success, lineWidth: 1.6, duration: 0.7).frame(width: 34, height: 34)
            VStack(alignment: .leading, spacing: 6) {
                Text("Today's set is done").font(Typeface.headline(18)).lineLimit(1).minimumScaleFactor(0.85)
                if next.isEmpty {
                    Text("Every task checked correct and nothing is waiting. Reviews come back on schedule.").font(Typeface.sans(13.5)).foregroundStyle(Theme.secondary)
                } else {
                    Text("If you want to keep going, Genesis plans these next:").font(Typeface.sans(13.5)).foregroundStyle(Theme.secondary)
                    ForEach(next.prefix(4), id: \.self) { Text("· " + $0).font(Typeface.sans(12.5)).foregroundStyle(Theme.secondary).lineLimit(1) }
                }
            }
            Spacer()
            if next.isEmpty {
                Button("Extra practice") { model.page = .practice }.secondaryAction()
            } else {
                Button("Plan the next set") { model.requestSync() }.primaryAction()
            }
        }
        .card(padding: 24, radius: 18)
    }
}

struct EmptyPlan: View {
    @EnvironmentObject var model: AppModel
    var title: String
    var detail: String
    var showSync: Bool
    var body: some View {
        HStack(spacing: 22) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(Typeface.headline(18)).lineLimit(1).minimumScaleFactor(0.85)
                Text(detail).font(Typeface.sans(13.5)).foregroundStyle(Theme.secondary)
            }
            Spacer()
            if showSync { Button("Sync now") { model.requestSync() }.primaryAction() }
        }
        .card(padding: 24, radius: 18)
    }
}


/// Under "Tell Genesis", once you've written a note on the Mac and never sent one from the phone:
/// the iPhone app is the faster way. "Not now" hides it for a week; the first phone note ends it.
struct PhoneNudge: View {
    @EnvironmentObject var model: AppModel
    @State private var snoozedUntil = UserDefaults.standard.object(forKey: "phoneNudgeSnoozed") as? Date ?? .distantPast
    @State private var hover = false

    private static let lines: [(String, String)] = [
        ("Say it from your seat.", "Get Genesis on your iPhone and send notes mid-lecture. Your plan's already fixed by the time you're home."),
        ("Class moved the test?", "Tell Genesis from your phone the moment it happens. No waiting till you're back at your Mac."),
        ("Your Mac can't come to class.", "Your phone can. Send notes from your seat and Genesis reshapes today around them."),
    ]
    @State private var line = PhoneNudge.lines.randomElement()!

    var body: some View {
        if !model.phoneSeen && !model.notes.isEmpty && snoozedUntil < Date() {
            HStack(alignment: .center, spacing: 14) {
                Image(systemName: "iphone.gen3.radiowaves.left.and.right")
                    .font(.system(size: 18)).foregroundStyle(Theme.focus)
                    .frame(width: 40, height: 40).background(Theme.focus.opacity(0.1), in: RoundedRectangle(cornerRadius: 11, style: .continuous))
                VStack(alignment: .leading, spacing: 3) {
                    Text(line.0).font(Typeface.sans(13.5, .medium))
                    Text(line.1).font(Typeface.sans(12)).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                VStack(alignment: .trailing, spacing: 6) {
                    Button("Get the iPhone app") { model.openIPhoneApp() }.primaryAction()
                    Button("Not now") {
                        let until = Date().addingTimeInterval(7 * 86400)
                        UserDefaults.standard.set(until, forKey: "phoneNudgeSnoozed")
                        withAnimation(.easeOut(duration: 0.2)) { snoozedUntil = until }
                    }
                    .buttonStyle(QuietButtonStyle())
                }
            }
            .padding(14)
            .background(Theme.raised, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Theme.focus.opacity(hover ? 0.45 : 0.25), lineWidth: 1))
            .onHover { hover = $0 }
            .transition(.opacity.combined(with: .move(edge: .top)))
        }
    }
}
