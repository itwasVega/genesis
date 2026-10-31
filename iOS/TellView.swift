import SwiftUI
import UniformTypeIdentifiers

/// The whole app: the orb, the classes, a line of text, and the orb taking it in.
struct TellView: View {
    @Environment(Inbox.self) private var inbox

    private enum Stage: Equatable { case idle, composing(Course), absorbed }

    @State private var stage: Stage = .idle
    @State private var text = ""
    @FocusState private var typing: Bool

    // Feeding animation
    @State private var flying: String?
    @State private var flyT: CGFloat = 0
    @State private var orbPresses = 0
    @State private var fedCount = 0
    @State private var orbFrame: CGRect = .zero
    @State private var fieldFrame: CGRect = .zero
    @State private var placeholder = ""
    @State private var showSetup = false
    // Rapid fire: every message in one sitting shares a session; the tab ends it.
    @State private var session = UUID().uuidString.lowercased()
    @State private var sentCount = 0
    @State private var tabPull: CGFloat = 0
    @Environment(\.openURL) private var openURL

    private let examples = ["Missed today's lecture", "Proofs by induction lost me", "Quiz moved to Friday", "Exam covers chapters 4–6"]

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            VStack(spacing: 0) {
                header.padding(.top, 18)
                Spacer(minLength: 12)
                OrbView(successID: fedCount, pressID: orbPresses)
                    .frame(maxWidth: 340, maxHeight: 340)
                    .layoutPriority(-1)
                    .onGeometryChange(for: CGRect.self) { $0.frame(in: .named("screen")) } action: { orbFrame = $0 }
                    .contentShape(Circle())
                    .onTapGesture { orbPresses += 1; if isComposing { cancelCompose() } }
                    .accessibilityHidden(true)
                Spacer(minLength: 12)
                bottom.padding(.horizontal, 20).padding(.bottom, 34)
            }

            if let flying {
                Text(flying)
                    .font(.system(size: 15))
                    .lineLimit(2)
                    .foregroundStyle(Palette.ink)
                    .padding(.horizontal, 16).padding(.vertical, 10)
                    .glassPanel(Capsule())
                    .frame(maxWidth: 300)
                    .scaleEffect(1 - 0.92 * flyT)
                    .opacity(1 - Double(pow(flyT, 3)))
                    .blur(radius: 5 * flyT)
                    .position(x: lerp(fieldFrame.midX, orbFrame.midX, flyT), y: lerp(fieldFrame.midY, orbFrame.midY, flyT))
                    .allowsHitTesting(false)
            }
        }
        .coordinateSpace(.named("screen"))
        // Test hook (simulator only, via a launch argument): open setup automatically.
        .onAppear {
            if UserDefaults.standard.bool(forKey: "genesisTestPicker") { showSetup = true }
            // Simulator verification: fire the real success event, then a repeat mid-glow.
            // Simulator verification of the composer: open CS1, type, then press Return.
            if UserDefaults.standard.bool(forKey: "genesisTestCompose"), let first = inbox.courses.first {
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { open(first); text = "test 3 will include related rates" }
                DispatchQueue.main.asyncAfter(deadline: .now() + 3) { text += "\n" }                                   // Return = send
                DispatchQueue.main.asyncAfter(deadline: .now() + 4) { text = "didn't understand implicit differentiation\n" }
                DispatchQueue.main.asyncAfter(deadline: .now() + 5) { text = "also includes optimization" }
                DispatchQueue.main.asyncAfter(deadline: .now() + 6.5) { finishSession() }                              // what the swipe-down tab calls
            }
            if UserDefaults.standard.bool(forKey: "genesisTestSuccess") {
                DispatchQueue.main.asyncAfter(deadline: .now() + 22) { fedCount += 1 }
                DispatchQueue.main.asyncAfter(deadline: .now() + 23.5) { fedCount += 1 }
                DispatchQueue.main.asyncAfter(deadline: .now() + 32) {
                    let out = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("orb-stats.txt")
                    try? (OrbStats.shared.summary + "\n--- glow trace (s, value)\n" + OrbStats.shared.glowTrace).write(to: out, atomically: true, encoding: .utf8)
                }
            }
        }
        .sensoryFeedback(.success, trigger: fedCount)
        .sheet(isPresented: $showSetup) { SetupSheet().environment(inbox).presentationDetents([.large]).presentationBackground(.black) }
        .animation(.spring(response: 0.45, dampingFraction: 0.85), value: stage)
    }

    private var isComposing: Bool { if case .composing = stage { return true } else { return false } }

    // MARK: Header

    private var header: some View {
        VStack(spacing: 8) {
            Text(stage == .absorbed ? "Absorbed." : "Tell Genesis.")
                .font(Fonts.title(46))
                .foregroundStyle(Palette.ink)
                .contentTransition(.opacity)
            Text(subtitle)
                .font(.system(size: 14))
                .foregroundStyle(Palette.secondary)
                .multilineTextAlignment(.center)
                .contentTransition(.opacity)
            if inbox.waiting > 0 && stage == .idle {   // never mid-burst: it would open Shortcuts
                Button { deliver() } label: {
                    Text("\(inbox.waiting) WAITING — TAP TO SEND").font(Fonts.label(10)).tracking(1.2).foregroundStyle(Palette.tertiary)
                }
            }
        }
        .padding(.horizontal, 28)
        .animation(.easeOut(duration: 0.35), value: stage)
    }

    private var subtitle: String {
        switch stage {
        case .idle: return "Whatever you tell it shapes your next plan."
        case .composing(let c): return sentCount == 0 ? "About \(c.label). Return sends; keep going." : "\(sentCount) sent. Keep going, or swipe the tab down when you're done."
        case .absorbed: return "Genesis puts your messages together and weaves them into your next plan."
        }
    }

    // MARK: Bottom

    @ViewBuilder
    private var bottom: some View {
        if case .composing(let course) = stage {
            composer(course)
            if let problem = inbox.problem { Text(problem).font(.system(size: 12)).foregroundStyle(.red) }
        } else {
            VStack(spacing: 12) {
                if inbox.courses.isEmpty {
                    Text("Add your classes in Genesis on your Mac, then connect its shared folder.")
                        .font(.system(size: 14)).foregroundStyle(Palette.secondary).multilineTextAlignment(.center)
                }
                Text("WHICH CLASS").font(Fonts.label(10)).tracking(1.6).foregroundStyle(Palette.tertiary)
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], spacing: 12) {
                    ForEach(inbox.courses) { c in
                        Button { open(c) } label: {
                            Text(c.label).font(.system(size: 19, weight: .medium)).frame(maxWidth: .infinity).padding(.vertical, 18)
                        }
                        .glassButton()
                    }
                }
            }
            .opacity(stage == .absorbed ? 0.35 : 1)
            .disabled(stage == .absorbed)
            if (!inbox.connected && !inbox.shortcutReady) || inbox.problem != nil {
                Button { showSetup = true } label: {
                    Text(inbox.problem ?? "One-time setup: connect to your Mac")
                        .font(.system(size: 12)).foregroundStyle(inbox.problem == nil ? Palette.tertiary : .red.opacity(0.85)).underline()
                }
                .padding(.top, 4)
            }
        }
    }

    private func composer(_ course: Course) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            // The "done for now" tab, like the home indicator: swipe it down to finish.
            VStack(spacing: 6) {
                Capsule().fill(Palette.ink.opacity(0.55)).frame(width: 134, height: 5)
                Text(sentCount == 0 ? "SWIPE DOWN WHEN DONE" : "\(sentCount) SENT · SWIPE DOWN WHEN DONE")
                    .font(Fonts.label(9.5)).tracking(1.3).foregroundStyle(Palette.tertiary)
            }
            .frame(maxWidth: .infinity).frame(height: 40)
            .contentShape(Rectangle())
            .offset(y: tabPull)
            .gesture(DragGesture(minimumDistance: 6)
                .onChanged { v in tabPull = max(0, min(v.translation.height, 60)) * 0.6 }
                .onEnded { v in
                    let done = v.translation.height > 34 || v.predictedEndTranslation.height > 90
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) { tabPull = 0 }
                    if done { finishSession() }
                })
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Done sending")
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { finishSession() }
            HStack {
                Text(course.label.uppercased()).font(Fonts.label(10)).tracking(1.4).foregroundStyle(Palette.secondary)
                Spacer()
            }
            HStack(alignment: .bottom, spacing: 10) {
                // Return sends this message straight into the orb; the keyboard stays up for the next one.
                TextField(placeholder, text: $text, axis: .vertical)
                    .font(.system(size: 17))
                    .lineLimit(1...5)
                    .focused($typing)
                    .submitLabel(.send)
                    .onChange(of: text) { _, new in
                        if new.contains("\n") { text = new.replacingOccurrences(of: "\n", with: " "); send() }
                    }
                    .accessibilityAction(named: "Send to Genesis", send)
                    .padding(.horizontal, 16).padding(.vertical, 12)
                    .glassPanel(RoundedRectangle(cornerRadius: 22, style: .continuous))
                    .onGeometryChange(for: CGRect.self) { $0.frame(in: .named("screen")) } action: { fieldFrame = $0 }
                Button { cancelCompose() } label: {
                    Image(systemName: "xmark").font(.system(size: 16, weight: .semibold)).frame(width: 30, height: 30)
                }
                .glassButton()
                .buttonBorderShape(.circle)
                .frame(minWidth: 44, minHeight: 44)          // Apple's minimum tap target
                .contentShape(Rectangle())
                .accessibilityLabel(text.isEmpty ? "Close" : "Clear")
            }
        }
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }

    // MARK: Feeding

    private func open(_ c: Course) {
        text = ""; sentCount = 0; session = UUID().uuidString.lowercased()
        placeholder = examples.randomElement() ?? ""; stage = .composing(c)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { typing = true }
    }

    /// One message: into the orb right away; the composer stays open for the next.
    private func send() {
        guard case .composing(let course) = stage else { return }
        let note = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !note.isEmpty else { text = ""; return }
        guard inbox.send(note, course: course, session: session, seq: sentCount) else { text = note; return }
        text = ""
        sentCount += 1
        flying = note; flyT = 0
        withAnimation(.easeIn(duration: 0.42)) { flyT = 1 } completion: {
            if flying == note { flying = nil }
            fedCount += 1            // the orb takes each message in and glows
        }
        typing = true
    }

    /// The tab was swiped down: send anything still typed, close the session, deliver.
    private func finishSession() {
        guard case .composing(let course) = stage else { return }
        if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            send()
            guard text.isEmpty else { return }
        }
        typing = false
        guard sentCount > 0 else { stage = .idle; return }
        guard inbox.endSession(session, course: course, count: sentCount) else { typing = true; return }
        stage = .absorbed
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.6) { if stage == .absorbed { stage = .idle } }
        // One hand-off for the whole burst (with no folder access this opens the Genesis Note shortcut once).
        if !UserDefaults.standard.bool(forKey: "genesisTestCompose") { DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { deliver() } }
    }

    /// X: clears what's typed; with nothing typed, closes (messages already sent are kept).
    private func cancelCompose() {
        if !text.isEmpty { text = ""; return }
        if sentCount > 0 { finishSession() } else { typing = false; stage = .idle }
    }

    private func deliver() {
        if inbox.connected { inbox.refresh(); return }      // folder access: notes were written directly
        guard let url = inbox.shortcutURL() else { return }
        openURL(url) { accepted in if !accepted { inbox.problem = "Shortcuts isn't available." } }
    }

    private func lerp(_ a: CGFloat, _ b: CGFloat, _ t: CGFloat) -> CGFloat { a + (b - a) * t }
}

// MARK: - Folder picker (presented directly, per Apple's sample)

@MainActor
enum FolderPicker {
    private static var delegate: Delegate?

    static func present(onPick: @escaping (URL) -> Void) {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.folder])
        let d = Delegate(onPick: onPick)
        delegate = d                       // the picker holds its delegate weakly
        picker.delegate = d
        let windows = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows)
        guard let root = (windows.first(where: \.isKeyWindow) ?? windows.first)?.rootViewController else { return }
        var top = root
        while let next = top.presentedViewController, !next.isBeingDismissed { top = next }
        top.present(picker, animated: true)
    }

    final class Delegate: NSObject, UIDocumentPickerDelegate {
        let onPick: (URL) -> Void
        init(onPick: @escaping (URL) -> Void) { self.onPick = onPick }
        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            if let url = urls.first { onPick(url) }
            FolderPicker.delegate = nil
        }
        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) { FolderPicker.delegate = nil }
    }
}

// MARK: - One-time setup

/// The Genesis Note shortcut: one action that saves what Genesis hands it into iCloud Drive › Genesis.
struct SetupSheet: View {
    @Environment(Inbox.self) private var inbox
    @State private var showDiagnostics = false
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL

    private let steps: [(String, String)] = [
        ("Open Shortcuts", "Tap + to make a new shortcut. Name it exactly Genesis Note."),
        ("Add Save File", "Search the actions for Save File and add it."),
        ("Save what Genesis sends", "Tap the first blue word in the action and choose Shortcut Input."),
        ("Choose the folder", "Tap the folder in the action and pick iCloud Drive › Genesis. Turn off Ask Where to Save."),
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack {
                    Text("Connect to your Mac").font(Fonts.title(34)).foregroundStyle(Palette.ink)
                    Spacer()
                    Button { dismiss() } label: { Image(systemName: "xmark").font(.system(size: 14, weight: .medium)) }.foregroundStyle(Palette.tertiary)
                }
                Text("Notes travel through iCloud Drive › Genesis to Genesis on your Mac.")
                    .font(.system(size: 14)).foregroundStyle(Palette.secondary)

                if inbox.connected {
                    Text("CONNECTED TO \(inbox.folderName?.uppercased() ?? "FOLDER")").font(Fonts.label(11)).tracking(1.2).foregroundStyle(Palette.secondary)
                }
                Button {
                    // Present on top of this sheet (presenting while it closes is silently refused).
                    FolderPicker.present { url in inbox.connect(url); if inbox.connected { dismiss() } }
                } label: { Text(inbox.connected ? "Choose a different folder" : "Choose iCloud Drive › Genesis").frame(maxWidth: .infinity).padding(.vertical, 6) }
                    .prominentGlassButton()
                Text("Go into the Genesis folder, then tap Open or Done.").font(.system(size: 12)).foregroundStyle(Palette.tertiary)

                Text("IF THE FOLDER WON'T OPEN").font(Fonts.label(10)).tracking(1.4).foregroundStyle(Palette.tertiary).padding(.top, 10)
                Text("Some sideloaded installs can't keep folder access. Use a one-action Shortcut instead; Genesis hops to it for a second after each note.")
                    .font(.system(size: 13)).foregroundStyle(Palette.secondary)
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(Array(steps.enumerated()), id: \.offset) { i, step in
                        HStack(alignment: .firstTextBaseline, spacing: 14) {
                            Text(String(format: "%02d", i + 1)).font(Fonts.label(11)).foregroundStyle(Palette.tertiary)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(step.0).font(.system(size: 15, weight: .medium)).foregroundStyle(Palette.ink)
                                Text(step.1).font(.system(size: 13)).foregroundStyle(Palette.secondary)
                            }
                        }
                    }
                }
                Button { openURL(URL(string: "shortcuts://create-shortcut")!) } label: { Text("Open Shortcuts").frame(maxWidth: .infinity).padding(.vertical, 6) }
                    .glassButton()
                Button { showDiagnostics = true } label: {
                    Text("Run folder picker diagnostics").font(.system(size: 12)).foregroundStyle(Palette.tertiary).underline()
                }
                .frame(maxWidth: .infinity)
                .padding(.top, 6)
            }
            .padding(26)
        }
        .sheet(isPresented: $showDiagnostics) { DiagnosticsView().presentationBackground(.black) }
        .onAppear {
            if UserDefaults.standard.bool(forKey: "genesisTestPicker") {
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { FolderPicker.present { url in inbox.connect(url) } }
            }
        }
    }
}

// MARK: - Liquid Glass (iOS 26+), material before that

extension View {
    @ViewBuilder func glassButton() -> some View {
        if #available(iOS 26.0, *) { self.buttonStyle(.glass) } else { self.buttonStyle(.bordered) }
    }
    @ViewBuilder func prominentGlassButton() -> some View {
        // Graphite tint: prominent without a bright accent color.
        if #available(iOS 26.0, *) { self.buttonStyle(.glassProminent).tint(Color(white: 0.24)) } else { self.buttonStyle(.borderedProminent).tint(Color(white: 0.24)) }
    }
    @ViewBuilder func glassPanel<S: Shape>(_ shape: S) -> some View {
        if #available(iOS 26.0, *) { self.glassEffect(.regular, in: shape) } else { self.background(.ultraThinMaterial, in: shape) }
    }
}
