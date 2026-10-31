import SwiftUI
import AppKit

// MARK: - The Genesis companion
//
// The same orb as the iPhone app, flying into the Genesis window like a small light that
// comes to you when you need it and drifts away when you don't. It never decides what to study
// (the planner does that); it walks you through it, one button at a time:
//   • your day is ready / welcome back → the one thing to start with
//   • you've stalled on a task → "Where do I start?", "Give me a hint", "Explain it another
//     way", "Check what I have", or type what's confusing
//   • an answer was checked → one true sentence about your progress, then it takes you on
//   • a note from your phone changed something → it rebuilds today's plan and tells you
//   • everything's done → today's wrap-up, and the next set if you want it
//   • the semester is over → goodbye for now
// It lives inside the Genesis window and is never called up: no button, menu or shortcut.
// It comes on its own at the moments it's needed, so its arrival always means something.

struct CompanionAction: Identifiable {
    let id = UUID()
    var label: String
    var primary = false
    var run: () -> Void
}

struct CompanionLine {
    var text: String
    var detail: [String] = []
    var actions: [CompanionAction] = []
    var help = false           // show the "I'm stuck" buttons
    var stay = false           // don't drift away on its own
    var chat = false           // a break conversation
}

struct ChatMessage: Identifiable, Hashable, Equatable { let id = UUID(); var who: String; var text: String }

@MainActor
final class Companion: ObservableObject {
    static let shared = Companion()

    @Published var line: CompanionLine?
    @Published var thinking = false
    @Published var reply: String?
    @Published var replyAction: String?
    @Published var question = ""
    @Published var glowID = 0
    @Published var pressID = 0
    @Published var hovering = false

    /// The face the orb's light gathers into. It reacts to what's happening (thinking while it
    /// writes, listening while you type) and otherwise shows the feeling of what was just said,
    /// then melts back into the swirl.
    @Published var mood = "neutral"
    private var moodWork: DispatchWorkItem?
    var face: String {
        if thinking { return "thinking" }
        if !chatDraft.isEmpty || !question.isEmpty { return "listening" }
        return mood
    }
    func feel(_ m: String, for seconds: Double = 7) {
        moodWork?.cancel()
        mood = m
        guard m != "neutral" else { return }
        let w = DispatchWorkItem { [weak self] in self?.mood = "neutral" }
        moodWork = w
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: w)
    }

    weak var model: AppModel?
    private var hideWork: DispatchWorkItem?
    private var timer: Timer?

    // What the orb has already reacted to, so it never repeats itself.
    private var lastActivity = Date()
    private var offeredHelpFor: [String: Date] = [:]
    private var seenBrief: String? = UserDefaults.standard.string(forKey: "companionSeenBrief")
    private var greetedDay: String? = UserDefaults.standard.string(forKey: "companionGreetedDay")
    private var wrappedBrief: String? = UserDefaults.standard.string(forKey: "companionWrappedBrief")
    private var seenFailure: String?
    private var lastDone = -1
    private var lastNudge = Date.distantPast
    private var nudges: (day: String, count: Int) = ("", 0)
    private var knownNotes: Set<String>?
    private var lastReplan = Date.distantPast
    private var advanceWork: DispatchWorkItem?

    // How you talk and how you study, learned on this Mac (school_hq_companion.py profile).
    private var lowercase = false
    private var periods = true
    private var breakAt: Double = 12          // minutes of focus before the orb steps in
    private var sessionStart: Date?
    private var breakTaken = false
    private var lastTyped = Date.distantPast
    @Published var chat: [ChatMessage] = []
    @Published var chatDraft = ""
    @Published var chatWrapped = false

    /// Every appearance starts with a choice: keep talking, or not now. Nothing opens until you say yes.
    @Published var engaged = false
    @Published var farewellLine: String?
    /// Small, unpredictable movements while it's with you (a hop, a sway, a lean), on the orb only.
    @Published var idleX: CGFloat = 0
    @Published var idleY: CGFloat = 0
    @Published var idleScale: CGFloat = 1
    @Published var idleTilt: Double = 0
    private var idleWork: DispatchWorkItem?
    private var lastCheckIn = UserDefaults.standard.object(forKey: "companionLastCheckIn") as? Date ?? .distantPast
    private var lastPicked: [String: String] = [:]
    /// Settings › Genesis companion: off for a while, or until you turn it back on. It's on by default.
    @Published var pausedUntil: Date? = UserDefaults.standard.object(forKey: "companionPausedUntil") as? Date
    var paused: Bool { (pausedUntil ?? .distantPast) > Date() }
    func pause(until date: Date?) {
        pausedUntil = date
        if let date { UserDefaults.standard.set(date, forKey: "companionPausedUntil") } else { UserDefaults.standard.removeObject(forKey: "companionPausedUntil") }
        if paused { hideWork?.cancel(); idleWork?.cancel(); flyOut() }
        objectWillChange.send()
    }
    @Published var choiceYes = "yeah"
    @Published var choiceNo = "not rn"

    /// Something new every time: a random line from the options, never the one it used last.
    func pick(_ key: String, _ options: [String]) -> String {
        let fresh = options.filter { $0 != lastPicked[key] }
        let line = (fresh.isEmpty ? options : fresh).randomElement() ?? options[0]
        lastPicked[key] = line
        return line
    }

    // MARK: Setup

    func attach(_ model: AppModel) {
        guard self.model == nil else { return }
        self.model = model
        // No button, menu or shortcut calls it: it comes on its own, when it's needed.
        timer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in Task { @MainActor in self?.tick() } }
        loadProfile()
        Timer.scheduledTimer(withTimeInterval: 1800, repeats: true) { [weak self] _ in Task { @MainActor in self?.loadProfile() } }
        let nc = NotificationCenter.default
        nc.addObserver(forName: NSApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in Task { @MainActor in self?.log("active") } }
        nc.addObserver(forName: NSApplication.didResignActiveNotification, object: nil, queue: .main) { [weak self] _ in Task { @MainActor in self?.log("inactive"); self?.sessionStart = nil } }
    }

    /// Picks up how you write and how long you usually focus.
    func loadProfile() {
        model?.runScript("school_hq_companion.py", ["profile"]) { [weak self] data in
            guard let self, let v = data.flatMap({ try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }) else { return }
            let st = v["style"] as? [String: Any] ?? [:], hb = v["habits"] as? [String: Any] ?? [:]
            self.lowercase = st["lowercase"] as? Bool ?? false
            self.periods = st["periods"] as? Bool ?? true
            self.breakAt = (hb["break_at_minutes"] as? Double) ?? Double(hb["break_at_minutes"] as? Int ?? 12)
        }
    }

    /// Talks the way you do: lowercase if you write lowercase, no full stop if you don't.
    func say(_ text: String) -> String {
        var t = text
        if lowercase {
            t = t.split(separator: "`", omittingEmptySubsequences: false).enumerated().map { $0.offset % 2 == 1 ? String($0.element) : $0.element.lowercased() }.joined(separator: "`")
        }
        if !periods, t.hasSuffix("."), !t.hasSuffix("...") { t.removeLast() }
        return t
    }

    /// The activity log the habits come from (on this Mac only): what you're doing, never what you type.
    func log(_ event: String, task: String? = nil) {
        guard let model, model.connected else { return }
        let url = model.outputs.appendingPathComponent("School HQ Study/activity.jsonl")
        var e: [String: Any] = ["t": ISO8601DateFormatter().string(from: Date()), "e": event]
        if let t = task ?? model.openTask?.exerciseID { e["task"] = t }
        guard let data = try? JSONSerialization.data(withJSONObject: e), var line = String(data: data, encoding: .utf8) else { return }
        line += "\n"
        if let h = try? FileHandle(forWritingTo: url) { _ = try? h.seekToEnd(); h.write(Data(line.utf8)); try? h.close() }
        else { try? Data(line.utf8).write(to: url) }
    }

    // MARK: Showing and hiding

    func show(_ line: CompanionLine, glow: Bool = false, linger: TimeInterval = 14, bringForward: Bool = false) {
        guard let model, !model.farewell, !paused else { return }
        reply = nil; replyAction = nil; question = ""; farewellLine = nil
        // A fresh appearance asks first; a follow-up while you're already talking doesn't.
        if !visible { engaged = false }
        choiceYes = sayLabel(pick("yes", ["yeah", "ok talk to me", "go on", "i'm listening", "sure", "yeah what's up", "hm ok"]))
        choiceNo = sayLabel(pick("no", ["not rn", "later", "i'm good", "maybe later", "nah i'm locked in", "another time"]))
        withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) { self.line = line }
        if glow { glowID += 1 } else { pressID += 1 }
        flyIn(bringForward)
        scheduleHide(line.stay || line.help ? nil : linger)
    }

    func dismiss() {
        hideWork?.cancel()
        flyOut()
    }

    /// "Not now": it takes it well, says so in a few words, and goes.
    func notNow() {
        withAnimation(orbSpring) { farewellLine = say(pick("bye", ["all good. i'll be around", "bet. go get it", "ok ok, leaving you to it", "say less", "got it. i'm close if you need me", "cool cool. later"])) }
        feel(["playful", "happy"].randomElement()!, for: 2.5)
        hideWork?.cancel()
        let w = DispatchWorkItem { [weak self] in self?.flyOut() }
        hideWork = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.9, execute: w)
    }

    /// "Yeah": the conversation opens. A line without its own next step becomes a chat you lead.
    func yes() {
        withAnimation(orbSpring) { engaged = true }
        scheduleHide(nil)
        if let line, !line.chat, !line.help, line.actions.isEmpty {
            let opener = line.text
            withAnimation(orbSpring) {
                self.line = CompanionLine(text: "", chat: true)
                chat = opener.isEmpty ? [] : [ChatMessage(who: "genesis", text: opener)]
                chatDraft = ""; chatWrapped = false
            }
        }
    }

    private func scheduleHide(_ after: TimeInterval?) {
        hideWork?.cancel()
        guard let after else { return }
        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            if self.hovering || self.thinking || self.reply != nil { self.scheduleHide(6); return }
            self.flyOut()
        }
        hideWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + after, execute: work)
    }

    /// Tapping the orb while it's with you (there is no other way to call it).
    func summon() {
        if visible && line != nil { dismiss(); return }
        show(contextLine(), linger: 30, bringForward: true)
    }

    /// What the orb offers when you call it, given where you are.
    func contextLine() -> CompanionLine {
        guard let model else { return CompanionLine(text: say("i'm here.")) }
        if let task = model.openTask, model.status(task) != .correct {
            return CompanionLine(text: say(pick("here", ["I'm here. What's got you?", "Hey. Which part's being annoying?", "Ok I'm here. Talk to me.", "Need a hand with this one?"])), help: true)
        }
        if model.busy { return CompanionLine(text: say("Putting today together right now. Give me a minute, I'll come get you.")) }
        if model.syncFailed {
            return CompanionLine(text: say("Couldn't finish checking your classes. Your plan from before is still here."),
                                 actions: [CompanionAction(label: sayLabel("Try again"), primary: true) { [weak self] in self?.model?.requestSync(); self?.dismiss() }])
        }
        if !model.planIsToday || model.tasks.isEmpty {
            return CompanionLine(text: say("Let me get today ready. Takes a few minutes, I'll come back when it's done."),
                                 actions: [CompanionAction(label: sayLabel("Get today ready"), primary: true) { [weak self] in self?.model?.requestSync(); self?.dismiss() }])
        }
        if let next = model.nextTask { return startLine(next, lead: model.doneCount == 0 ? "Ok, here's where we start." : "Next one's ready.") }
        return CompanionLine(text: say("You're done for today. Rest, or want me to line up more?"),
                             actions: [CompanionAction(label: sayLabel("Line up more"), primary: true) { [weak self] in self?.model?.requestSync(); self?.dismiss() },
                                       CompanionAction(label: sayLabel("I'm done for today")) { [weak self] in self?.notNow() }])
    }

    private func startLine(_ task: StudyTask, lead: String) -> CompanionLine {
        CompanionLine(text: say(lead) + " " + task.title.replacingOccurrences(of: "`", with: ""),
                      detail: [Theme.courseLabel(task.courseID) + Theme.sep + minutesLabel(task.minutes)],
                      actions: [CompanionAction(label: sayLabel("Start"), primary: true) { [weak self] in self?.open(task) },
                                CompanionAction(label: sayLabel("In a bit")) { [weak self] in self?.notNow() }])
    }

    func sayLabel(_ label: String) -> String { lowercase ? label.lowercased() : label }

    func open(_ task: StudyTask) {
        NSApp.activate(ignoringOtherApps: true)
        NSApp.windows.first { $0.isVisible && !($0 is NSPanel) }?.makeKeyAndOrderFront(nil)
        model?.page = .today
        model?.openTask = task
        noteActivity()
        dismiss()
    }

    // MARK: Moments

    func noteActivity(_ kind: String = "type") {
        let now = Date()
        if model?.openTask != nil {
            if sessionStart == nil || now.timeIntervalSince(lastActivity) > 300 { sessionStart = now; breakTaken = false }
            if kind != "type" || now.timeIntervalSince(lastTyped) > 60 { log(kind); if kind == "type" { lastTyped = now } }
        }
        lastActivity = now
    }

    func taskChanged(_ task: StudyTask?) {
        objectWillChange.send()   // the resting orb follows whether a task is open
        if let task { log("open", task: task.exerciseID); noteActivity("open") } else { log("close"); sessionStart = nil }
    }

    /// Called whenever the app reloads its state.
    func observe() {
        guard let model, !model.farewell else { return }
        // A failed sync is explained once, with what to do about it.
        if model.syncFailed, let id = model.state?.request?.id, id != seenFailure {
            seenFailure = id
            show(CompanionLine(text: say("Couldn't finish checking your classes" + (model.syncProblem.map { ": " + $0.text } ?? ".") + " Your plan from before is still here."),
                               actions: [CompanionAction(label: sayLabel("Try again"), primary: true) { [weak self] in self?.model?.requestSync(); self?.dismiss() }]), linger: 25)
            return
        }
        guard !model.busy, model.planIsToday, let brief = model.brief else { return }
        // A new plan: say so, and hand over the first step.
        if brief.id != seenBrief {
            let wasFirst = seenBrief == nil
            seenBrief = brief.id; UserDefaults.standard.set(brief.id, forKey: "companionSeenBrief")
            greetedDay = AppModel.todayString; UserDefaults.standard.set(greetedDay, forKey: "companionGreetedDay")
            if let next = model.nextTask {
                let lead = model.doneCount > 0 ? pick("more", ["Lined up the next set.", "More's ready if you want it.", "Ok, round two's ready."])
                    : (wasFirst ? "Hey, I'm Genesis. Today's ready." : pick("ready", ["Today's ready.", "Ok, today's all set.", "Your day's ready. Not too bad either.", "Today's ready. Start small?", "Plan's done."]))
                show(startLine(next, lead: lead), glow: true, linger: 40)
            }
            lastDone = model.doneCount
            return
        }
        // Back for the day: welcome back with the next step.
        if greetedDay != AppModel.todayString, let next = model.nextTask {
            greetedDay = AppModel.todayString; UserDefaults.standard.set(greetedDay, forKey: "companionGreetedDay")
            show(startLine(next, lead: pick("back", ["Hey, you're back.", "Look who's here.", "Oh hey. Missed you a little.", "There you are.", "Welcome back."])), linger: 30)
        }
        // Everything done: wrap up the day once.
        let done = model.doneCount
        if done == model.tasks.count, !model.tasks.isEmpty, lastDone >= 0, lastDone < done, wrappedBrief != brief.id {
            wrappedBrief = brief.id; UserDefaults.standard.set(brief.id, forKey: "companionWrappedBrief")
            wrapUp()
        }
        lastDone = done
        watchNotes()
    }

    /// After an answer is checked: one honest sentence, then onward.
    func graded(_ data: Data?, exerciseID: String) {
        guard let model, let data, let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let latest = obj["latest"] as? [String: Any], let outcome = latest["outcome"] as? String else { return }
        let remark = obj["remark"] as? String
        noteActivity("check")
        if outcome == "correct" {
            let next = model.tasks.first { model.status($0) != .correct && $0.exerciseID != exerciseID }
            var actions: [CompanionAction] = []
            if let next {
                actions = [CompanionAction(label: sayLabel("Next"), primary: true) { [weak self] in self?.advanceWork?.cancel(); self?.open(next) },
                           CompanionAction(label: sayLabel("Stay here")) { [weak self] in self?.advanceWork?.cancel(); self?.notNow() }]
                // Hands-free: it moves you on by itself unless you choose to stay.
                let work = DispatchWorkItem { [weak self] in
                    guard let self, self.model?.openTask?.exerciseID == exerciseID || self.model?.openTask?.parent == exerciseID else { return }
                    self.open(next)
                    self.show(self.startLine(next, lead: "Next one."), linger: 8)
                }
                advanceWork = work
                DispatchQueue.main.asyncAfter(deadline: .now() + 6, execute: work)
            }
            feel("happy", for: 8)
            show(CompanionLine(text: remark ?? say("That's right."), detail: next == nil ? [] : [say("Taking you to the next one…")], actions: actions), glow: true, linger: 9)
        } else {
            let error = latest["specific_error"] as? String
            // Right after a miss is when you'd stall, so it stays with the help ready.
            feel("empathetic", for: 9)
            show(CompanionLine(text: remark ?? say("Not yet. That's okay."), detail: error.map { [say("The fix: ") + $0] } ?? [], help: true))
        }
    }

    private func wrapUp() {
        model?.runScript("school_hq_companion.py", ["summary"]) { [weak self] data in
            guard let self, let model = self.model else { return }
            let v = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
            let lines = v["lines"] as? [String] ?? []
            if v["semester_over"] as? Bool == true {
                self.show(CompanionLine(text: self.say("That's everything. And it looks like your finals are behind you."), detail: lines,
                                        actions: [CompanionAction(label: sayLabel("Say goodbye for now"), primary: true) { [weak self] in self?.dismiss(); model.setFarewell(true) },
                                                  CompanionAction(label: sayLabel("Not yet")) { [weak self] in self?.notNow() }], stay: true), glow: true)
                return
            }
            let more = !(model.coverage?.deferred ?? []).isEmpty || model.coverage?.obligations.contains { $0.topics.contains { $0.plan == "later" } } == true
            var actions = [CompanionAction(label: sayLabel("I'm done for today"), primary: !more) { [weak self] in self?.notNow() }]
            if more { actions.insert(CompanionAction(label: sayLabel("Keep going"), primary: true) { [weak self] in self?.model?.requestSync(); self?.dismiss() }, at: 0) }
            self.feel("proud", for: 10)
            self.show(CompanionLine(text: self.say("That's everything for today. Proud of you."), detail: lines, actions: actions), glow: true, linger: 45)
        }
    }

    /// A note from your phone or the Mac that changes the plan (a missed class, a moved date,
    /// what a test covers): today's plan is rebuilt for you, and the orb says so.
    private func watchNotes() {
        guard let model else { return }
        let ids = Set(model.notes.map(\.id))
        defer { knownNotes = ids }
        guard let known = knownNotes else { return }
        let fresh = model.notes.filter { !known.contains($0.id) }
        let changing = fresh.filter { $0.chips.contains { ["missed_class", "date_report", "scope_hint", "struggling"].contains($0.kind) && $0.course != nil } }
        guard !changing.isEmpty, !model.busy, Date().timeIntervalSince(lastReplan) > 1800 else { return }
        lastReplan = Date()
        model.requestSync()
        let what = changing.count == 1 ? "your note" : "your \(changing.count) notes"
        show(CompanionLine(text: say("Got " + what + ". Reshaping today around it, I'll show you when it's ready.")), linger: 12)
    }

    /// Every 20 seconds: about to drift, stuck on a task, or away while something's due?
    private func tick() {
        guard let model, !model.farewell, !thinking else { return }
        let now = Date()
        // About to drift: a little before the point where you usually stop, the orb starts
        // talking about something else entirely. A short break that doesn't feel like one,
        // then straight back to the exact task.
        if NSApp.isActive, let task = model.openTask, ![.correct, .checking].contains(model.status(task)), let start = sessionStart,
           !breakTaken, !visible, now.timeIntervalSince(lastActivity) < 120, now.timeIntervalSince(start) >= breakAt * 60 {
            breakTaken = true
            startChat()
            return
        }
        // Stuck: nothing written two minutes into a task, or three quiet minutes after you
        // started writing. It comes to you; there is no button to call it.
        let empty = model.openTask.map { (model.drafts[$0.exerciseID] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && (model.attachments[$0.exerciseID] ?? []).isEmpty } ?? true
        if NSApp.isActive, let task = model.openTask, ![.correct, .checking].contains(model.status(task)),
           now.timeIntervalSince(lastActivity) > (empty ? 120 : 180), now.timeIntervalSince(offeredHelpFor[task.exerciseID] ?? .distantPast) > 480, !visible {
            offeredHelpFor[task.exerciseID] = now
            show(CompanionLine(text: say(model.drafts[task.exerciseID]?.isEmpty == false
                ? pick("stuckDraft", ["Hey. Want me to look at what you have so far?", "You've got something there. Want a second pair of eyes?", "Pausing on this one? I can check what you have."])
                : pick("stuckEmpty", ["Not sure where to start? I got you.", "Blank page staring back? Same. I can help.", "This one's being quiet huh. Want a way in?", "Hey. Want the first step?"])), help: true))
            return
        }
        // Out of nowhere, like a friend texting to check in: now and then (at most every few
        // hours), while you're in the app but not in the middle of a task.
        if NSApp.isActive, model.openTask == nil, !visible, now.timeIntervalSince(lastCheckIn) > 4 * 3600,
           now.timeIntervalSince(lastActivity) < 600, Double.random(in: 0..<1) < 1.0 / 45 {
            lastCheckIn = now; UserDefaults.standard.set(now, forKey: "companionLastCheckIn")
            startChat(moment: "check_in")
            return
        }
        // The iPhone app, once in a while, in its own words: never during a task, at most twice
        // (five days apart), and never again once a note has come in from the phone.
        let pitched = UserDefaults.standard.integer(forKey: "companionPhonePitches")
        let lastPitch = UserDefaults.standard.object(forKey: "companionPhonePitchedAt") as? Date ?? .distantPast
        if NSApp.isActive, !model.phoneSeen, pitched < 2, model.openTask == nil, !visible, model.planIsToday,
           now.timeIntervalSince(lastPitch) > 5 * 86400, now.timeIntervalSince(lastActivity) < 600, Double.random(in: 0..<1) < 1.0 / 60 {
            UserDefaults.standard.set(pitched + 1, forKey: "companionPhonePitches"); UserDefaults.standard.set(now, forKey: "companionPhonePitchedAt")
            show(CompanionLine(text: say(pick("phone", ["psst. I live on your phone too. text me from class and the plan's fixed before you're back",
                                                           "ngl I get lonely when you're in lecture. get me on your iPhone and send me notes from your seat",
                                                           "test moved? missed something? you can tell me right from class if you grab the iPhone app"])),
                               actions: [CompanionAction(label: sayLabel("Get the iPhone app"), primary: true) { [weak self] in self?.model?.openIPhoneApp(); self?.dismiss() },
                                         CompanionAction(label: sayLabel(pick("phoneNo", ["maybe later", "not rn", "later"]))) { [weak self] in self?.notNow() }]), linger: 30)
            return
        }
        // Away from Genesis while something is due within a day: one gentle nudge, at most
        // twice a day, never at night.
        let hour = Calendar.current.component(.hour, from: now)
        let day = AppModel.todayString
        if nudges.day != day { nudges = (day, 0) }
        if !NSApp.isActive, (10...21).contains(hour), nudges.count < 2, now.timeIntervalSince(lastNudge) > 3 * 3600,
           now.timeIntervalSince(lastActivity) > 3 * 3600, model.planIsToday, let next = model.nextTask,
           let soon = model.coverage?.obligations.first(where: { $0.days <= 1 && $0.topics.contains { $0.exercise_id != nil && !model.isCorrect($0.exercise_id) } }) {
            lastNudge = now; nudges.count += 1
            model.notify("Genesis", "Quick one before " + Theme.courseLabel(soon.course) + " " + soon.name + "? " + next.title.replacingOccurrences(of: "`", with: ""))
            show(CompanionLine(text: say("Quick one before " + Theme.courseLabel(soon.course) + " " + soon.name + (soon.days == 0 ? " today?" : " tomorrow?")),
                               detail: [next.title.replacingOccurrences(of: "`", with: "") + Theme.sep + minutesLabel(next.minutes)],
                               actions: [CompanionAction(label: sayLabel("Let's do it"), primary: true) { [weak self] in self?.open(next) },
                                         CompanionAction(label: sayLabel("Later")) { [weak self] in self?.notNow() }], stay: true))   // waits in the window until you're back
        }
    }

    // MARK: Break chat

    private var moment = "break"
    func startChat(moment: String = "break") {
        self.moment = moment
        chat = []; chatDraft = ""; chatWrapped = false
        show(CompanionLine(text: "", chat: true), linger: 0)
        scheduleHide(nil)
        continueChat()
    }

    func sendChat() {
        let text = chatDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !thinking else { return }
        withAnimation(orbSpring) { chat.append(ChatMessage(who: "you", text: text)) }; chatDraft = ""
        continueChat()
    }

    private func continueChat() {
        guard let model else { return }
        thinking = true
        let history = chat.map { ["who": $0.who, "text": $0.text] }
        var payload: [String: Any] = ["history": history, "moment": moment]
        if let t = model.openTask { payload["task"] = ["title": t.title.replacingOccurrences(of: "`", with: ""), "course": t.courseID] }
        let pulse = Timer.scheduledTimer(withTimeInterval: 1.8, repeats: true) { [weak self] _ in Task { @MainActor in self?.pressID += 1 } }
        model.runScript("school_hq_companion.py", ["chat"], stdin: try? JSONSerialization.data(withJSONObject: payload)) { [weak self] data in
            pulse.invalidate()
            guard let self else { return }
            self.thinking = false
            let v = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
            guard let text = v["reply"] as? String else {
                // Never leave you hanging: without the model it still checks in, in its own words.
                if self.chat.isEmpty {
                    withAnimation(orbSpring) { self.chat = [ChatMessage(who: "genesis", text: self.say(self.pick("offline", ["hey. just checking on you", "ok you've been at it a while. i'm here", "ngl i like this time of night", "checking in. that's it, that's the message"])))] }
                } else { self.chatWrapped = true }
                return
            }
            withAnimation(orbSpring) { self.chat.append(ChatMessage(who: "genesis", text: text)) }
            self.feel(v["mood"] as? String ?? "neutral", for: 9)
            self.glowID += 1
            // You lead: it goes as long as you want, and wraps when you sound ready.
            if v["wrap"] as? Bool == true || self.chat.filter({ $0.who == "genesis" }).count >= 14 { self.chatWrapped = true }
        }
    }

    /// Back to the exact task you were on, with a fresh focus clock.
    func backToWork() {
        sessionStart = Date(); breakTaken = false
        dismiss()
        if let t = model?.openTask { model?.openTask = t }
    }

    // MARK: Help when you're stuck

    func ask(_ kind: String) {
        guard let model, let task = model.openTask, let brief = model.brief else {
            reply = say("Open a task and I'll help you with it."); return
        }
        thinking = true; reply = nil; replyAction = nil; noteActivity("help")
        scheduleHide(nil)
        let payload: [String: Any] = ["brief_id": brief.id, "exercise_id": task.exerciseID, "kind": kind,
                                      "draft": model.drafts[task.exerciseID] ?? "", "question": kind == "ask" ? question : ""]
        let pulse = Timer.scheduledTimer(withTimeInterval: 1.8, repeats: true) { [weak self] _ in Task { @MainActor in self?.pressID += 1 } }
        model.runScript("school_hq_companion.py", ["help"], stdin: try? JSONSerialization.data(withJSONObject: payload)) { [weak self] data in
            pulse.invalidate()
            guard let self else { return }
            self.thinking = false
            let v = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
            if let text = v["reply"] as? String {
                withAnimation(.easeOut(duration: 0.25)) { self.reply = text; self.replyAction = v["next_action"] as? String }
                self.feel(kind == "check" ? "thinking" : "empathetic", for: 6)
                if v["used_help"] as? Bool == true { model.usedHelp.insert(task.exerciseID) }
                self.glowID += 1
            } else {
                self.reply = (v["error"] as? String) ?? self.say("Couldn't think that through just now. Try once more in a sec.")
            }
            self.question = ""
            self.scheduleHide(120)
        }
    }

    // MARK: Flight inside the Genesis window
    //
    // The orb lives in the app: it flies in over the page, settles in the corner of the
    // window, floats while it's with you, and flies back out when it's done. The flight uses
    // SwiftUI's built-in offset and opacity animations (x and y on different curves give
    // the arc), so no view code runs per frame and the Metal orb keeps its full frame rate.

    @Published var present = false     // the orb is in the window
    @Published var arrived = false     // settled: the conversation may show
    @Published var flyX: CGFloat = 0
    @Published var flyY: CGFloat = 0
    @Published var flyAlpha: Double = 0
    @Published var flyScale: CGFloat = 1
    @Published var speakID = 0          // the orb stirs as its words appear, and as you type
    /// While you're working, a small orb rests in the corner, breathing: it never leaves you.
    var resting: Bool { model?.openTask != nil && !(model?.farewell ?? false) && !paused }
    @Published var leaving = false
    private var visible: Bool { present && !leaving }

    /// Only an explicit call brings Genesis to the front; the orb never steals focus.
    private func flyIn(_ bringForward: Bool) {
        if bringForward {
            NSApp.activate(ignoringOtherApps: true)
            NSApp.windows.first { $0.isVisible && $0.canBecomeMain }?.makeKeyAndOrderFront(nil)
        }
        if visible { return }
        let reduce = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        leaving = false
        let waking = resting && !present
        if !present {
            var t = Transaction(); t.disablesAnimations = true
            withTransaction(t) {
                if waking { flyX = 0; flyY = 0; flyAlpha = 0.7; flyScale = 0.5 }   // it was already here, resting
                else { flyX = reduce ? 0 : 340; flyY = reduce ? 0 : 60; flyAlpha = 0; flyScale = 1 }
                arrived = false; present = true
            }
        }
        DispatchQueue.main.async {
            if waking {
                // Wakes where it was: grows, brightens, stirs, then speaks.
                withAnimation(.spring(response: 0.6, dampingFraction: 0.7)) { self.flyScale = 1; self.flyAlpha = 1 }
                self.pressID += 1
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { if !self.leaving { self.hello(); withAnimation(orbSpring) { self.arrived = true } } }
                return
            }
            if reduce {
                withAnimation(.easeOut(duration: 0.25)) { self.flyAlpha = 1 }
                self.arrived = true; return
            }
            self.enter(self.pick("entrance", Companion.entrances))
        }
    }

    static let entrances = ["swoop", "rise", "drop", "zip", "pop", "loop", "peek"]

    /// It makes its presence known: a different arrival every time, then a little hello.
    private func enter(_ style: String) {
        var t = Transaction(); t.disablesAnimations = true
        withTransaction(t) {
            switch style {
            case "rise": flyX = 0; flyY = 260; flyAlpha = 0; flyScale = 0.7
            case "drop": flyX = -40; flyY = -420; flyAlpha = 0; flyScale = 0.85
            case "zip":  flyX = 520; flyY = -30; flyAlpha = 0; flyScale = 0.9
            case "pop":  flyX = 0; flyY = 0; flyAlpha = 0; flyScale = 0.05
            case "loop": flyX = 380; flyY = 40; flyAlpha = 0; flyScale = 0.8
            case "peek": flyX = 170; flyY = 0; flyAlpha = 0; flyScale = 1
            default:     flyX = 340; flyY = 60; flyAlpha = 0; flyScale = 1
            }
        }
        var settle = 0.8
        switch style {
        case "rise":
            withAnimation(.spring(response: 0.75, dampingFraction: 0.55)) { flyY = 0; flyScale = 1 }
            withAnimation(.easeOut(duration: 0.35)) { flyAlpha = 1 }
            settle = 0.75
        case "drop":
            withAnimation(.spring(response: 0.7, dampingFraction: 0.45)) { flyY = 0; flyX = 0 }
            withAnimation(.easeOut(duration: 0.3)) { flyAlpha = 1; flyScale = 1 }
        case "zip":
            withAnimation(.spring(response: 0.45, dampingFraction: 0.5)) { flyX = 0; flyY = 0; flyScale = 1 }
            withAnimation(.easeOut(duration: 0.2)) { flyAlpha = 1 }
            settle = 0.55
        case "pop":
            withAnimation(.spring(response: 0.42, dampingFraction: 0.42)) { flyScale = 1; flyAlpha = 1 }
            glowID += 1
            settle = 0.5
        case "loop":
            // A little loop-the-loop on the way in.
            withAnimation(.easeOut(duration: 0.3)) { flyAlpha = 1; flyScale = 1 }
            withAnimation(.timingCurve(0.3, 0, 0.4, 1, duration: 0.42)) { flyX = 60; flyY = -170 } completion: {
                withAnimation(.timingCurve(0.4, 0, 0.6, 1, duration: 0.32)) { self.flyX = -60; self.flyY = -90 } completion: {
                    withAnimation(.spring(response: 0.5, dampingFraction: 0.62)) { self.flyX = 0; self.flyY = 0 }
                }
            }
            settle = 1.2
        case "peek":
            // Peeks in, ducks back a little, then comes all the way.
            withAnimation(.easeOut(duration: 0.35)) { flyAlpha = 1; flyX = 90 } completion: {
                withAnimation(.easeInOut(duration: 0.25)) { self.flyX = 140 } completion: {
                    withAnimation(.spring(response: 0.5, dampingFraction: 0.55)) { self.flyX = 0 }
                }
            }
            settle = 1.1
        default:
            // x glides in and settles; y rises first, then floats down: an arc.
            withAnimation(.timingCurve(0.15, 0.6, 0.25, 1, duration: 1.05)) { flyX = 0 }
            withAnimation(.timingCurve(0.3, 0, 0.3, 1, duration: 0.5)) { flyY = -150 } completion: {
                withAnimation(.timingCurve(0.35, 0, 0.25, 1, duration: 0.6)) { self.flyY = 0 }
            }
            withAnimation(.easeOut(duration: 0.4)) { flyAlpha = 1 }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + settle) { [weak self] in
            guard let self, !self.leaving else { return }
            self.hello()
            withAnimation(.spring(response: 0.4, dampingFraction: 0.86)) { self.arrived = true }
        }
    }

    /// The unmistakable part: a bright pulse, a bounce, a face, and (unless you turned it off) a soft sound.
    private func hello() {
        glowID += 1
        withAnimation(.spring(response: 0.22, dampingFraction: 0.5)) { idleScale = 1.14 } completion: {
            withAnimation(.spring(response: 0.45, dampingFraction: 0.55)) { self.idleScale = 1 }
        }
        if mood == "neutral" { feel(["happy", "playful", "curious"].randomElement()!, for: 2.8) }
        if !UserDefaults.standard.bool(forKey: "companionQuiet"), let sound = NSSound(named: NSSound.Name(["Pop", "Tink", "Purr", "Bottle"].randomElement()!)) {
            sound.volume = 0.28; sound.play()
        }
        scheduleIdle()
    }

    /// Alive between words: every few seconds, something small and never the same twice in a row.
    private func scheduleIdle() {
        idleWork?.cancel()
        let w = DispatchWorkItem { [weak self] in
            guard let self, self.visible else { return }
            if !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion && !self.thinking {
                self.gesture(self.pick("gesture", ["hop", "sway", "lean", "tilt", "glance", "bob", "stretch", "still", "still"]))
            }
            self.scheduleIdle()
        }
        idleWork = w
        DispatchQueue.main.asyncAfter(deadline: .now() + Double.random(in: 2.6...7.5), execute: w)
    }

    private func gesture(_ g: String) {
        switch g {
        case "hop":
            withAnimation(.easeOut(duration: 0.18)) { idleY = -CGFloat.random(in: 9...18) } completion: {
                withAnimation(.spring(response: 0.38, dampingFraction: 0.45)) { self.idleY = 0 }
            }
        case "sway":
            let d = CGFloat.random(in: 6...12) * (Bool.random() ? 1 : -1)
            withAnimation(.easeInOut(duration: 0.6)) { idleX = d } completion: { withAnimation(.easeInOut(duration: 0.8)) { self.idleX = 0 } }
        case "lean":
            withAnimation(.spring(response: 0.5, dampingFraction: 0.7)) { idleScale = 1.06; idleX = -6 } completion: {
                withAnimation(.spring(response: 0.6, dampingFraction: 0.8)) { self.idleScale = 1; self.idleX = 0 }
            }
        case "tilt":
            withAnimation(.spring(response: 0.5, dampingFraction: 0.6)) { idleTilt = Double.random(in: 6...12) * (Bool.random() ? 1 : -1) } completion: {
                withAnimation(.spring(response: 0.7, dampingFraction: 0.7)) { self.idleTilt = 0 }
            }
        case "glance":
            if mood == "neutral" && chatDraft.isEmpty { feel("curious", for: 1.6) }
        case "bob":
            withAnimation(.easeInOut(duration: 0.35)) { idleY = 5 } completion: {
                withAnimation(.easeInOut(duration: 0.35)) { self.idleY = -5 } completion: { withAnimation(.easeInOut(duration: 0.4)) { self.idleY = 0 } }
            }
        case "stretch":
            withAnimation(.spring(response: 0.35, dampingFraction: 0.5)) { idleScale = 0.93 } completion: {
                withAnimation(.spring(response: 0.4, dampingFraction: 0.45)) { self.idleScale = 1.05 } completion: {
                    withAnimation(.spring(response: 0.5, dampingFraction: 0.8)) { self.idleScale = 1 }
                }
            }
            pressID += 1
        default: break
        }
    }

    private func flyOut() {
        guard visible else { return }
        leaving = true
        idleWork?.cancel(); idleX = 0; idleY = 0; idleScale = 1; idleTilt = 0
        let reduce = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        withAnimation(.easeOut(duration: 0.18)) { arrived = false }
        if resting {
            // Back to resting in its corner, not gone.
            withAnimation(.spring(response: 0.55, dampingFraction: 0.85)) { flyScale = 0.5 }
            withAnimation(.easeIn(duration: 0.5)) { flyAlpha = 0 } completion: { [weak self] in
                guard let self, self.leaving else { return }
                self.present = false; self.leaving = false; self.flyScale = 1
                self.line = nil; self.reply = nil; self.thinking = false
            }
            return
        }
        withAnimation(.timingCurve(0.5, 0, 0.75, 0.4, duration: reduce ? 0.2 : 0.8)) { flyX = reduce ? 0 : 360; flyY = reduce ? 0 : -240 }
        withAnimation(.easeIn(duration: reduce ? 0.2 : 0.7)) { flyAlpha = 0 } completion: { [weak self] in
            guard let self, self.leaving else { return }
            self.present = false; self.leaving = false
            self.line = nil; self.reply = nil; self.thinking = false
        }
    }
}

// MARK: - What the orb shows: words floating out of it

/// Every new message, the typing dots and the cursor arrive on this spring, so the
/// thread grows out of the orb and older lines glide up instead of jumping.
let orbSpring = Animation.spring(response: 0.58, dampingFraction: 0.84)

struct CompanionView: View {
    @EnvironmentObject var companion: Companion

    var body: some View {
        if !companion.present && companion.resting {
            RestingOrb().transition(.opacity.animation(.easeInOut(duration: 0.6)))
        }
        if companion.present {
            HStack(alignment: .bottom, spacing: 2) {
                if let line = companion.line, companion.arrived {
                    conversation(line)
                        .transition(.asymmetric(insertion: .scale(scale: 0.3, anchor: .bottomTrailing).combined(with: .opacity).combined(with: .offset(x: 24)),
                                                removal: .scale(scale: 0.6, anchor: .bottomTrailing).combined(with: .opacity)))
                }
                FloatingOrb()
            }
            .animation(orbSpring, value: companion.arrived)
            .animation(orbSpring, value: companion.chat)
            .animation(orbSpring, value: companion.thinking)
            .animation(orbSpring, value: companion.reply)
            .animation(orbSpring, value: companion.engaged)
            .animation(orbSpring, value: companion.farewellLine)
            .scaleEffect(companion.flyScale, anchor: .bottomTrailing)
            .offset(x: companion.flyX, y: companion.flyY)
            .opacity(companion.flyAlpha)
            .onHover { companion.hovering = $0 }
            .environment(\.colorScheme, .dark)
        }
    }

    /// Genesis's words are bubbles with their tail on the orb; yours are just words and a cursor.
    private func conversation(_ line: CompanionLine) -> some View {
        VStack(alignment: .trailing, spacing: 7) {
            if !line.text.isEmpty { Spoken(text: line.text) }
            ForEach(line.detail, id: \.self) { d in Spoken(text: d, small: true) }
            if let bye = companion.farewellLine {
                if line.chat, let last = companion.chat.last(where: { $0.who == "genesis" }) { Spoken(text: last.text) }
                Spoken(text: bye)
            } else if !line.actions.isEmpty {
                // Its own two choices (start / in a bit) are already the yes and the no.
                if companion.reply == nil {
                    QuickReplies { ForEach(line.actions) { a in Button(a.label) { a.run() }.buttonStyle(OrbButtonStyle(primary: a.primary)) } }
                }
            } else if line.chat {
                chatArea
            } else if !companion.engaged {
                // First, a choice: keep talking, or not now. No X; it takes "not now" well.
                QuickReplies {
                    Button(companion.choiceYes) { companion.yes() }.buttonStyle(OrbButtonStyle(primary: true))
                    Button(companion.choiceNo) { companion.notNow() }.buttonStyle(OrbButtonStyle(primary: false))
                }
            } else if line.help {
                helpArea
            }
        }
        .frame(width: 300, alignment: .trailing)
        .padding(.bottom, 34)          // the last bubble's tail lands on the orb
    }

    @ViewBuilder private var chatArea: some View {
        ForEach(companion.chat.suffix(8)) { m in
            if m.who == "you" { Said(text: m.text) } else { Spoken(text: m.text) }
        }
        if companion.thinking {
            TypingBubble()
        } else if !companion.engaged && companion.chat.count == 1 {
            QuickReplies {
                Button(companion.choiceYes) { companion.yes() }.buttonStyle(OrbButtonStyle(primary: true))
                Button(companion.choiceNo) { companion.notNow() }.buttonStyle(OrbButtonStyle(primary: false))
            }
        } else if companion.chatWrapped {
            QuickReplies { Button(companion.sayLabel("Back to it")) { companion.backToWork() }.buttonStyle(OrbButtonStyle(primary: true)) }
        } else if companion.chat.last?.who == "genesis" {
            ReplyCursor(text: $companion.chatDraft) { companion.sendChat() }
            Button(companion.model?.openTask == nil ? companion.sayLabel("gotta go") : companion.sayLabel("Back to it")) { companion.backToWork() }.buttonStyle(.plain).font(Typeface.sans(11)).foregroundStyle(.white.opacity(0.4))
        }
    }

    @ViewBuilder private var helpArea: some View {
        if companion.thinking {
            TypingBubble()
        } else if let reply = companion.reply {
            Spoken(text: reply)
            if let next = companion.replyAction, !next.isEmpty { Spoken(text: companion.say("Next: ") + next, small: true) }
            QuickReplies {
                Button(companion.sayLabel("Got it")) { companion.notNow() }.buttonStyle(OrbButtonStyle(primary: true))
                Button(companion.sayLabel("Another hint")) { companion.ask("hint") }.buttonStyle(OrbButtonStyle(primary: false))
            }
        } else {
            QuickReplies {
                Button(companion.say("Where do I start?")) { companion.ask("start") }.buttonStyle(OrbButtonStyle(primary: false))
                Button(companion.sayLabel("Give me a hint")) { companion.ask("hint") }.buttonStyle(OrbButtonStyle(primary: false))
                Button(companion.sayLabel("Explain it another way")) { companion.ask("explain") }.buttonStyle(OrbButtonStyle(primary: false))
                Button(companion.sayLabel("Check what I have")) { companion.ask("check") }.buttonStyle(OrbButtonStyle(primary: false))
            }
            ReplyCursor(text: $companion.question) {
                if !companion.question.trimmingCharacters(in: .whitespaces).isEmpty { companion.ask("ask") }
            }
        }
    }
}

// MARK: - Message pieces

/// Something Genesis says: a dark-glass bubble whose tail points back at the orb, growing
/// out of it, with the words typing themselves out.
struct Spoken: View {
    var text: String
    var small = false
    var body: some View {
        TypewriterText(text: text, size: small ? 12.5 : 14.5, color: .white.opacity(small ? 0.62 : 0.96))
            .padding(.horizontal, 14).padding(.vertical, small ? 7 : 10)
            .background(BubbleShape(tailOnRight: true).fill(Color(white: 0.16).opacity(0.95)))
            .background(BubbleShape(tailOnRight: true).fill(.ultraThinMaterial))
            .overlay(BubbleShape(tailOnRight: true).stroke(.white.opacity(0.07), lineWidth: 0.5))
            .shadow(color: .black.opacity(0.28), radius: 12, y: 5)
            .padding(.leading, 30)
            .transition(.asymmetric(insertion: .scale(scale: 0.2, anchor: .bottomTrailing).combined(with: .opacity).combined(with: .offset(x: 18, y: 10)),
                                    removal: .opacity))
    }
}

/// What you said: just your words, no bubble.
struct Said: View {
    var text: String
    var body: some View {
        Text(text).font(Typeface.sans(14.5)).foregroundStyle(.white.opacity(0.62))
            .multilineTextAlignment(.trailing)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .trailing)
            .padding(.trailing, 14)
            .transition(.opacity.combined(with: .offset(y: 6)))
    }
}

/// "Genesis is typing": three dots breathing in a bubble that grows out of the orb.
struct TypingBubble: View {
    @State private var on = false
    var body: some View {
        HStack(spacing: 5) {
            ForEach(0..<3) { i in
                Circle().fill(.white).frame(width: 6.5, height: 6.5)
                    .opacity(on ? 0.85 : 0.25)
                    .animation(.easeInOut(duration: 0.55).repeatForever().delay(Double(i) * 0.18), value: on)
            }
        }
        .padding(.horizontal, 15).padding(.vertical, 13)
        .background(BubbleShape(tailOnRight: true).fill(Color(white: 0.16).opacity(0.95)))
        .background(BubbleShape(tailOnRight: true).fill(.ultraThinMaterial))
        .onAppear { on = true }
        .transition(.asymmetric(insertion: .scale(scale: 0.2, anchor: .bottomTrailing).combined(with: .opacity).combined(with: .offset(x: 18, y: 10)), removal: .opacity))
    }
}

/// Text that writes itself out, a character at a time. The bubble is sized for the whole
/// message from the start, so it never jitters while the words appear.
struct TypewriterText: View {
    var text: String
    var size: CGFloat
    var color: Color
    @State private var shown = 0
    @State private var task: Task<Void, Never>?

    private var clean: String { text.replacingOccurrences(of: "`", with: "").replacingOccurrences(of: "**", with: "") }

    var body: some View {
        let chars = Array(clean)
        let solid = max(0, shown - 3)
        // The newest letters fade in rather than pop, so the words seem to flow out.
        var t = Text(String(chars.prefix(solid))).foregroundColor(color)
        for (k, i) in (solid..<min(shown, chars.count)).enumerated() {
            t = t + Text(String(chars[i])).foregroundColor(color.opacity([0.75, 0.45, 0.2][min(2, shown - 1 - i)] + 0.0 * Double(k)))
        }
        t = t + Text(String(chars.dropFirst(shown))).foregroundColor(.clear)
        return t
            .font(Typeface.sans(size))
            .fixedSize(horizontal: false, vertical: true)
            .onAppear { start() }
            .onChange(of: text) { _, _ in shown = 0; start() }
            .onDisappear { task?.cancel() }
    }

    private func start() {
        task?.cancel()
        let chars = Array(clean)
        if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion { shown = chars.count; return }
        task = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 180_000_000)   // let the bubble finish growing out of the orb
            while shown < chars.count + 3, !Task.isCancelled {
                shown += 1
                if shown % 9 == 0 { Companion.shared.speakID += 1 }   // the orb stirs as it talks
                if shown > chars.count { try? await Task.sleep(nanoseconds: 30_000_000); continue }
                let c = chars[shown - 1]
                let pause: UInt64 = ".!?".contains(c) ? 170 : ",;:".contains(c) ? 90 : c == " " ? 26 : 16
                try? await Task.sleep(nanoseconds: pause * 1_000_000)
            }
        }
    }
}

/// No box to type in: after Genesis speaks, a bright blinking cursor appears, and your words
/// appear beside it as you type, on the orb's side. Return sends.
struct ReplyCursor: View {
    @Binding var text: String
    var send: () -> Void
    @FocusState private var focused: Bool
    @State private var lit = true
    @State private var lastKey = Date.distantPast
    private let blink = Timer.publish(every: 0.53, on: .main, in: .common).autoconnect()

    /// A solid rounded bar (a template image, so it takes the text color and sits on the baseline).
    static let bar: NSImage = {
        let img = NSImage(size: NSSize(width: 3, height: 19), flipped: false) { r in
            NSColor.white.setFill(); NSBezierPath(roundedRect: r, xRadius: 1.5, yRadius: 1.5).fill(); return true
        }
        img.isTemplate = true
        return img
    }()

    var body: some View {
        ZStack(alignment: .topTrailing) {
            // The real text field only listens for your keys; what you see is drawn below.
            TextField("", text: $text)
                .textFieldStyle(.plain).focused($focused).onSubmit(send)
                .frame(width: 1, height: 1).opacity(0.011)
                .onChange(of: text) { old, new in
                    lastKey = Date(); lit = true
                    if new.count > old.count && new.count % 4 == 0 { Companion.shared.speakID += 1 }   // it listens as you type
                }
            (Text(text).foregroundColor(.white.opacity(0.92)) + Text(" ").font(.system(size: 3)) + Text(Image(nsImage: ReplyCursor.bar)).baselineOffset(-3).foregroundColor(.white.opacity(lit || !focused ? 1 : 0.06)))
                .font(Typeface.sans(15.5))
                .multilineTextAlignment(.trailing)
                .shadow(color: .white.opacity(lit ? 0.55 : 0), radius: 6)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .trailing)
                .animation(.easeInOut(duration: 0.18), value: lit)
        }
        .padding(.top, 8).padding(.trailing, 14)
        .contentShape(Rectangle())
        .onTapGesture { focused = true }
        .onReceive(blink) { _ in lit = Date().timeIntervalSince(lastKey) < 0.6 ? true : !lit }   // solid while typing
        .onAppear { DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { focused = true } }
        .transition(.opacity)
    }
}

/// Quick-reply pills under the last message, wrapping as needed.
struct QuickReplies<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View { FlowLayout(spacing: 7) { content }.padding(.top, 4).padding(.leading, 30) }
}

/// A message bubble with a small tail at the bottom corner, iMessage-style.
struct BubbleShape: Shape {
    var tailOnRight: Bool
    func path(in r: CGRect) -> Path {
        let radius: CGFloat = min(18, r.height / 2)
        var p = Path(roundedRect: r, cornerRadius: radius, style: .continuous)
        // tail
        let x = tailOnRight ? r.maxX : r.minX, s: CGFloat = tailOnRight ? 1 : -1
        var t = Path()
        t.move(to: CGPoint(x: x - s * 10, y: r.maxY - 12))
        t.addQuadCurve(to: CGPoint(x: x + s * 5, y: r.maxY + 1), control: CGPoint(x: x - s * 2, y: r.maxY - 1))
        t.addQuadCurve(to: CGPoint(x: x - s * 14, y: r.maxY - 3), control: CGPoint(x: x - s * 6, y: r.maxY + 1))
        t.closeSubpath()
        p.addPath(t)
        return p
    }
}

struct FlowLayout: Layout {
    var spacing: CGFloat = 8
    var trailing = true          // lines hug the orb's side
    private func lines(_ width: CGFloat, _ subviews: Subviews) -> [[(Int, CGSize)]] {
        var out: [[(Int, CGSize)]] = [[]]; var x: CGFloat = 0
        for (i, s) in subviews.enumerated() {
            let size = s.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width { out.append([]); x = 0 }
            out[out.count - 1].append((i, size)); x += size.width + spacing
        }
        return out
    }
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 300
        let ls = lines(width, subviews)
        let h = ls.reduce(CGFloat(0)) { $0 + ($1.map { $0.1.height }.max() ?? 0) } + spacing * CGFloat(max(0, ls.count - 1))
        return CGSize(width: width, height: h)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for line in lines(bounds.width, subviews) {
            let w = line.reduce(CGFloat(0)) { $0 + $1.1.width } + spacing * CGFloat(max(0, line.count - 1))
            var x = trailing ? bounds.maxX - w : bounds.minX
            let h = line.map { $0.1.height }.max() ?? 0
            for (i, size) in line { subviews[i].place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size)); x += size.width + spacing }
            y += h + spacing
        }
    }
}

/// The orb itself. Its gentle float is a Core Animation loop on its own layer (no per-frame
/// view updates), so the Metal rendering runs at the display's full refresh rate.
struct FloatingOrb: View {
    @EnvironmentObject var companion: Companion
    var body: some View {
        OrbView(successID: companion.glowID, pressID: companion.pressID,
                configuration: OrbConfiguration(pace: 2.1, breathe: 1), floating: true, speakID: companion.speakID, mood: companion.face)
            .frame(width: 118, height: 118)
            .contentShape(Circle())
            .rotationEffect(.degrees(companion.idleTilt))
            .scaleEffect(companion.idleScale)
            .offset(x: companion.idleX, y: companion.idleY)
            .onTapGesture { companion.line == nil ? companion.summon() : companion.notNow() }
            .help("Genesis")
            .frame(width: 124, height: 124)
    }
}

/// While you work: the orb, small and dim in the corner, breathing and drifting a little.
/// It can't be clicked; it's just there.
struct RestingOrb: View {
    var body: some View {
        OrbView(configuration: OrbConfiguration(intensity: 0.8, pace: 1.3, breathe: 1), floating: true, calm: true)
            .frame(width: 60, height: 60)
            .opacity(0.72)
            .allowsHitTesting(false)
            .frame(width: 124, height: 124, alignment: .bottomTrailing)
            .padding(.trailing, 2).padding(.bottom, 2)
            .accessibilityHidden(true)
    }
}

/// Quick-reply pills: a soft white one for the main choice, faint glass for the rest.
struct OrbButtonStyle: ButtonStyle {
    var primary: Bool
    func makeBody(configuration: Configuration) -> some View { OrbPill(configuration: configuration, primary: primary) }
}

private struct OrbPill: View {
    let configuration: ButtonStyleConfiguration
    let primary: Bool
    @State private var hover = false
    var body: some View {
        configuration.label
            .font(Typeface.sans(12.5, .medium))
            .foregroundStyle(primary ? Color.black.opacity(0.88) : Color.white.opacity(hover ? 1 : 0.88))
            .padding(.horizontal, 14).padding(.vertical, 7.5)
            .background(Capsule().fill(primary ? Color.white.opacity(configuration.isPressed ? 0.7 : 0.93) : Color(white: 0.16).opacity(configuration.isPressed ? 1 : hover ? 0.98 : 0.9)))
            .background(Capsule().fill(.ultraThinMaterial))
            .overlay(Capsule().strokeBorder(.white.opacity(primary ? 0 : hover ? 0.2 : 0.1), lineWidth: 1))
            .contentShape(Capsule())
            .onHover { hover = $0 }
            .animation(.easeOut(duration: 0.15), value: hover)
    }
}

// MARK: - Goodbye for now

/// When the semester is over: a black window and the orb, breathing. The first time it says
/// one line; after that it is only the orb, waiting to be clicked.
struct FarewellView: View {
    @EnvironmentObject var model: AppModel
    @State private var pulse = 0
    @State private var showLine = false
    @State private var menu = false
    @State private var timer: Timer?

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            VStack(spacing: 26) {
                OrbView(successID: pulse, pressID: 0)
                    .frame(width: 260, height: 260)
                    .contentShape(Circle())
                    .onTapGesture { menu = true }
                    .popover(isPresented: $menu, arrowEdge: .bottom) {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Hi again.").font(Typeface.headline(16))
                            Button("Start a new semester") { menu = false; model.setFarewell(false); model.requestSync() }.primaryAction()
                            Button("Keep resting") { menu = false }.secondaryAction()
                        }
                        .padding(18)
                    }
                Text("Goodbye for now. Click me whenever you need me.")
                    .font(Typeface.sans(15)).foregroundStyle(.white.opacity(0.7))
                    .opacity(showLine ? 1 : 0)
            }
        }
        .onAppear {
            timer = Timer.scheduledTimer(withTimeInterval: 4.2, repeats: true) { _ in Task { @MainActor in pulse += 1 } }
            if !UserDefaults.standard.bool(forKey: "farewellSeen") {
                UserDefaults.standard.set(true, forKey: "farewellSeen")
                withAnimation(.easeIn(duration: 1.6).delay(1.2)) { showLine = true }
                DispatchQueue.main.asyncAfter(deadline: .now() + 9) { withAnimation(.easeOut(duration: 2)) { showLine = false } }
            }
        }
        .onDisappear { timer?.invalidate() }
    }
}
