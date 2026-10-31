import SwiftUI

// Guided practice from the original lesson bank (checked locally, no model).

struct PracticeInput: Codable { var kind: String; var placeholder: String?; var choices: [String]? }
struct PracticeQuestion: Codable { var id: String; var prompt: String; var blocks: [PromptBlock]?; var input: PracticeInput? }
struct PracticeLesson: Codable {
    var id: String
    var course: String
    var title: String
    var phase: String?
    var cue: String?
    var token: String
    var lesson_seen: Bool?
    var hint_used: Bool?
    var teaching_blocks: [PromptBlock]?
    var example_blocks: [PromptBlock]?
    var hint_blocks: [PromptBlock]?
    var question: PracticeQuestion
}
struct PracticeFeedback: Codable { var id: String?; var outcome: String; var feedback: String; var blocks: [PromptBlock]?; var lesson_id: String? }
struct PracticeState: Codable {
    var reason: String?
    var lesson: PracticeLesson?
    var feedback: PracticeFeedback?
    var attempts_in_session: Int?
    var next_review: String?
    var validation_message: String?
}

struct PracticeView: View {
    @EnvironmentObject var model: AppModel
    @State private var state: PracticeState?
    @State private var answer = ""
    @State private var busy = false
    @State private var error = ""
    @State private var showLearn = false
    @State private var showHint = false
    @State private var lastSubmittedID: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("PRACTICE").font(Typeface.label(10.5)).tracking(1.4).foregroundStyle(Theme.tertiary)
                    Text("Quick checks").font(Typeface.largeTitle()).lineLimit(1).minimumScaleFactor(0.8)
                    Text("Short original questions, checked instantly. Misses lead to the prerequisite, then a different question.")
                        .font(Typeface.sans(14)).foregroundStyle(Theme.secondary)
                }
                if busy && state == nil {
                    HStack(spacing: 12) { ScribbleLoader().frame(width: 40, height: 16); Text("Choosing your next question…").font(Typeface.sans(13)).shimmer() }
                }
                if let fb = state?.feedback, fb.id == lastSubmittedID {
                    feedbackCard(fb)
                }
                if let lesson = state?.lesson {
                    lessonCard(lesson)
                } else if state != nil {
                    HStack(spacing: 18) {
                        DrawOn(shape: SketchCheck(), color: Theme.success, lineWidth: 3).frame(width: 40, height: 40)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Nothing due right now").font(Typeface.headline(15)).lineLimit(1)
                            Text(state?.reason ?? "").font(Typeface.sans(13)).foregroundStyle(Theme.secondary)
                        }
                    }
                    .card()
                }
                if !error.isEmpty { Text(error).font(Typeface.sans(13)).foregroundStyle(Theme.error) }
            }
            .padding(.horizontal, 44).padding(.vertical, 40)
            .frame(maxWidth: 820, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .onAppear { if state == nil { act("next") } }
    }

    func lessonCard(_ l: PracticeLesson) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 6) {
                Tag(text: Theme.courseLabel(l.course))
                Tag(text: l.phase == "retention" ? "Spaced review" : l.phase == "checkpoint" ? "Checkpoint" : "Practice")
                Spacer()
            }
            Text(l.title).font(Typeface.headline(17)).lineLimit(1).minimumScaleFactor(0.85)
            if let r = state?.reason { InlineText(text: r, size: 13.5, color: Theme.secondary) }
            if let t = l.teaching_blocks, !t.isEmpty {
                if showLearn {
                    VStack(alignment: .leading, spacing: 12) {
                        Blocks(blocks: t, size: 15)
                        if let e = l.example_blocks, !e.isEmpty { SectionTitle(text: "Worked example"); Blocks(blocks: e, size: 15) }
                    }
                    .padding(16).background(Theme.well, in: RoundedRectangle(cornerRadius: 12))
                } else {
                    Button { showLearn = true; act("learn", ["token": l.token], reloadOnly: true) } label: { HStack(spacing: 7) { GlyphView(glyph: .page, size: 12); Text("Learn it first") } }
                        .buttonStyle(QuietButtonStyle())
                }
            }
            Blocks(blocks: l.question.blocks ?? [PromptBlock(kind: "paragraph", text: l.question.prompt, language: nil)], size: 15.5)
            if let choices = l.question.input?.choices, l.question.input?.kind == "choice" {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(choices, id: \.self) { c in
                        Button { answer = c } label: {
                            HStack {
                                ZStack { Circle().strokeBorder(lineWidth: 1.2); if answer == c { Circle().padding(3.5) } }.frame(width: 13, height: 13)
                                InlineText(text: c, size: 14)
                                Spacer()
                            }
                            .padding(12)
                            .background(answer == c ? Theme.sand : Theme.raised, in: RoundedRectangle(cornerRadius: 10))
                            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Theme.ring, lineWidth: 1))
                        }
                        .buttonStyle(.plain)
                    }
                }
            } else if l.question.input?.kind == "review" {
                LongAnswer(text: $answer, placeholder: "Write your full answer", mono: false) { submit(l) }
            } else {
                PillField(text: $answer, placeholder: l.question.input?.placeholder ?? "Your answer") { submit(l) }
            }
            if let v = state?.validation_message { Text(v).font(Typeface.sans(13)).foregroundStyle(Theme.error) }
            HStack(spacing: 12) {
                Button("Check") { submit(l) }.primaryAction().disabled(answer.trimmingCharacters(in: .whitespaces).isEmpty || busy)
                if let h = l.hint_blocks, !h.isEmpty {
                    if showHint { Blocks(blocks: h, size: 14.5) }
                    else { Button { showHint = true; act("hint", ["token": l.token], reloadOnly: true) } label: { HStack(spacing: 7) { GlyphView(glyph: .hint, size: 12); Text("Hint") } }.buttonStyle(QuietButtonStyle()) }
                }
                if busy { ScribbleLoader().frame(width: 36, height: 14) }
            }
            if let cue = l.cue { InlineText(text: "Cue: " + cue, size: 12.5, color: Theme.tertiary) }
        }
        .card(padding: 24, radius: 18)
        .id(l.token)
        .transition(.move(edge: .trailing).combined(with: .opacity))
    }

    func feedbackCard(_ fb: PracticeFeedback) -> some View {
        let ok = fb.outcome == "correct"
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Group { if ok { DrawOn(shape: SketchCheck(), color: Theme.success, lineWidth: 2.6) } else { DrawOn(shape: SketchCross(), color: Theme.error, lineWidth: 2.4) } }
                    .frame(width: 22, height: 22)
                Text(ok ? "Correct" : fb.outcome == "pending_review" ? "Saved for review" : "Not yet").font(Typeface.headline(15)).lineLimit(1)
            }
            Blocks(blocks: fb.blocks ?? [PromptBlock(kind: "paragraph", text: fb.feedback, language: nil)], size: 15, serif: false)
        }
        .padding(16)
        .background((ok ? Theme.success : Theme.error).opacity(0.07), in: RoundedRectangle(cornerRadius: 14))
        .transition(.opacity)
    }

    func submit(_ l: PracticeLesson) {
        let id = UUID().uuidString
        lastSubmittedID = id
        act("submit", ["token": l.token, "answer": answer, "id": id, "used_help": showHint || showLearn])
    }

    func act(_ action: String, _ payload: [String: Any]? = nil, reloadOnly: Bool = false) {
        busy = true; error = ""
        let data = payload.flatMap { try? JSONSerialization.data(withJSONObject: $0) }
        model.runScript("school_hq_learning.py", [action], stdin: data) { out in
            busy = false
            guard let out, let s = try? JSONDecoder().decode(PracticeState.self, from: out) else {
                error = "Practice could not load. Your answers are saved."; return
            }
            withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
                let changedQuestion = s.lesson?.token != state?.lesson?.token
                state = s
                if action == "submit" && s.validation_message == nil { answer = ""; showHint = false; showLearn = false }
                if changedQuestion && action != "submit" && !reloadOnly { answer = "" }
            }
        }
    }
}
