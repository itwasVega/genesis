import SwiftUI
import AppKit

@main
struct SchoolHQApp: App {
    @StateObject private var model = AppModel()

    init() { _ = Typeface.registered; CrashLog.install() }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
                .onAppear { model.setAppearance(model.appearance) }
                // The whole window is frosted: the desktop reads through, like the sidebar.
                .containerBackground(.ultraThinMaterial, for: .window)
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1180, height: 820)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandGroup(after: .appInfo) {
                Button("Sync") { model.requestSync() }.keyboardShortcut("s", modifiers: [.command, .shift]).disabled(model.busy)
                Button("Refresh") { model.reload() }.keyboardShortcut("r")
            }
        }

        Settings {
            SettingsView().environmentObject(model)
        }
    }
}

struct RootView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        if model.farewell {
            FarewellView().frame(minWidth: 640, minHeight: 480)
        } else {
            workspace
                // The companion orb lives in the window, above the page, out of the way of
                // the answer box and Check button while a task is open.
                .overlay(alignment: .bottomTrailing) {
                    CompanionView().environmentObject(Companion.shared)
                        .padding(.trailing, 18).padding(.bottom, model.openTask == nil ? 18 : 120)
                }
        }
    }

    var workspace: some View {
        NavigationSplitView {
            Sidebar()
                .navigationSplitViewColumnWidth(min: 210, ideal: 228, max: 260)
        } detail: {
            ZStack {
                CanvasBackground()
                Group {
                    if let task = model.openTask {
                        TaskView(task: task)
                            .id(task.exerciseID)
                            .transition(reduce ? .opacity : .asymmetric(insertion: .move(edge: .trailing).combined(with: .opacity), removal: .opacity))
                    } else {
                        switch model.page {
                        case .today: TodayView()
                        case .practice: PracticeView()
                        case .progress: ProgressPage()
                        case .library: LibraryView()
                        }
                    }
                }
                .animation(.spring(response: 0.42, dampingFraction: 0.86), value: model.openTask?.exerciseID)
            }
        }
        .foregroundStyle(Theme.ink)
        .frame(minWidth: 940, minHeight: 640)
        // The Canvas collector needs its web view in the window hierarchy.
        .background {
            if !model.canvasSignIn {
                CanvasWebView(canvas: model.canvas).frame(width: 1024, height: 720).opacity(0).allowsHitTesting(false).accessibilityHidden(true)
            }
        }
        .sheet(isPresented: $model.canvasSignIn) {
            CanvasSignIn(canvas: model.canvas) { model.canvasSignIn = false }
        }
        .sheet(isPresented: $model.choosingPlugins) {
            PluginPicker().environmentObject(model).interactiveDismissDisabled()
        }
    }
}

struct Sidebar: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            GenesisWordmark()
                .frame(height: 30)
                .padding(.top, 14).padding(.horizontal, 22).padding(.bottom, 30)

            VStack(spacing: 2) {
                nav(.today, "Today", .today)
                nav(.practice, "Practice", .practice)
                nav(.progress, "Progress", .progress)
                nav(.library, "Library", .library)
            }
            .padding(.horizontal, 12)

            Spacer()
            SyncCard().padding(12)
            HStack {
                SettingsLink { HStack(spacing: 9) { GlyphView(glyph: .settings, size: 13); Text("Settings").font(Typeface.sans(13)) } }
                    .buttonStyle(QuietButtonStyle())
                Spacer()
            }
            .padding(.horizontal, 12).padding(.bottom, 14)
        }
    }

    func nav(_ page: AppModel.Page, _ title: String, _ glyph: Glyph) -> some View {
        let selected = model.page == page && model.openTask == nil
        return Button {
            withAnimation(.easeInOut(duration: 0.2)) { model.openTask = nil; model.page = page }
        } label: {
            HStack(spacing: 12) {
                GlyphView(glyph: glyph, size: 14)
                Text(title).font(Typeface.sans(13.5, selected ? .medium : .regular))
                Spacer()
                if page == .today, let brief = model.brief, !brief.tasks.isEmpty {
                    Text("\(model.doneCount)/\(brief.tasks.count)").font(Typeface.label(10)).foregroundStyle(Theme.tertiary)
                }
            }
            .foregroundStyle(selected ? Theme.ink : Theme.secondary)
            .padding(.horizontal, 10).padding(.vertical, 8)
            .background(selected ? Theme.sand.opacity(0.7) : .clear, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(alignment: .leading) {
                // Active marker: a sliver of the orb's spectrum.
                if selected {
                    Capsule().fill(LinearGradient(colors: Theme.prismColors, startPoint: .top, endPoint: .bottom))
                        .frame(width: 2, height: 16).offset(x: -1)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// Sidebar sync status: progress bar + shimmering stage while running.
struct SyncCard: View {
    @EnvironmentObject var model: AppModel
    @ObservedObject private var canvasWatcher = CanvasWatcher.shared

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if model.busy {
                Text(model.syncLabel)
                    .font(Typeface.sans(12, .medium))
                    .lineLimit(2)
                    .shimmer()
                ProgressLine(value: model.syncFraction)
                Button("Cancel") { model.cancelSync() }.buttonStyle(QuietButtonStyle())
            } else if let problem = model.syncProblem {
                HStack(alignment: .top, spacing: 8) {
                    Circle().fill(Theme.error).frame(width: 6, height: 6).padding(.top, 5)
                    Text(problem.text).font(Typeface.sans(12)).foregroundStyle(Theme.secondary).lineLimit(5)
                }
                if problem.action == .canvas { Button("Sign in to Canvas") { model.canvasSignIn = true }.secondaryAction() }
                Button("Sync again") { model.requestSync() }.primaryAction()
            } else {
                Text("Synced " + shortDate(model.state?.last_successful_sync))
                    .font(Typeface.sans(12)).foregroundStyle(Theme.tertiary)
                Button { model.requestSync() } label: {
                    HStack(spacing: 8) { GlyphView(glyph: .sync, size: 12); Text("Sync") }.frame(maxWidth: .infinity)
                }
                .secondaryAction()
                .disabled(!model.connected)
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 8)   // no custom background: it sits in the system glass sidebar
        .animation(.easeInOut(duration: 0.25), value: model.busy)
    }
}

/// Re-renders the sync label when the Canvas collector posts a new step.
@MainActor final class CanvasWatcher: ObservableObject {
    static let shared = CanvasWatcher()
    @Published var tick = 0
    private var timer: Timer?
    init() { timer = Timer.scheduledTimer(withTimeInterval: 0.8, repeats: true) { [weak self] _ in Task { @MainActor in self?.tick += 1 } } }
}

/// Full stage list, shown on Today while a sync runs.
struct SyncPanel: View {
    @EnvironmentObject var model: AppModel
    @ObservedObject private var canvasWatcher = CanvasWatcher.shared

    var body: some View {
        let fraction = model.syncFraction ?? 0
        let current = model.state?.request?.progress?.step ?? "sources"
        let currentIndex = syncStages.firstIndex { $0.id == current } ?? 0
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Generating today's plan").font(Typeface.headline(16)).lineLimit(1)
                Spacer()
                Text("\(Int(fraction * 100))%").font(Typeface.mono(12)).foregroundStyle(Theme.tertiary).contentTransition(.numericText())
            }
            ProgressLine(value: fraction, height: 5)
            VStack(alignment: .leading, spacing: 10) {
                ForEach(Array(syncStages.enumerated()), id: \.element.id) { i, stage in
                    HStack(spacing: 10) {
                        ZStack {
                            if i < currentIndex {
                                DrawOn(shape: SketchCheck(), color: Theme.success, lineWidth: 2, duration: 0.35).frame(width: 14, height: 14)
                            } else if i == currentIndex {
                                Circle().fill(Theme.ink).frame(width: 6, height: 6)
                            } else {
                                Circle().strokeBorder(Theme.ring, lineWidth: 1).frame(width: 7, height: 7)
                            }
                        }
                        .frame(width: 16)
                        if i == currentIndex {
                            Text(model.syncLabel).font(Typeface.sans(13, .medium)).shimmer()
                        } else {
                            Text(stage.label).font(Typeface.sans(13)).foregroundStyle(i < currentIndex ? Theme.secondary : Theme.tertiary)
                        }
                    }
                }
            }
            HStack {
                Text("Your current plan stays usable until the new one is ready.").font(Typeface.sans(12)).foregroundStyle(Theme.tertiary)
                Spacer()
                Button("Cancel") { model.cancelSync() }.buttonStyle(QuietButtonStyle())
            }
        }
        .card(padding: 22)
    }
}

/// Writes a symbolized backtrace to <workspace>/tmp/crash.log when the app crashes,
/// so crashes can be diagnosed without macOS crash-report access.
enum CrashLog {
    nonisolated(unsafe) static var fd: Int32 = -1
    static func install() {
        if ProcessInfo.processInfo.environment["GENESIS_TEST_WORKSPACE"] != nil { return }
        let bundled = Bundle.main.url(forResource: "workspace", withExtension: "txt").flatMap { try? String(contentsOf: $0, encoding: .utf8) }?.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let ws = UserDefaults.standard.string(forKey: "schoolHQWorkspace") ?? bundled, !ws.isEmpty else { return }
        try? FileManager.default.createDirectory(atPath: ws + "/tmp", withIntermediateDirectories: true)
        fd = open(ws + "/tmp/crash.log", O_WRONLY | O_CREAT | O_APPEND, 0o644)
        guard fd >= 0 else { return }
        NSSetUncaughtExceptionHandler { e in
            let s = "\n=== exception \(Date()) \(e.name.rawValue): \(e.reason ?? "")\n" + e.callStackSymbols.joined(separator: "\n") + "\n"
            _ = s.withCString { write(CrashLog.fd, $0, strlen($0)) }
        }
        for sig in [SIGABRT, SIGSEGV, SIGBUS, SIGILL, SIGTRAP, SIGFPE] {
            signal(sig) { s in
                let head = "\n=== signal \(s) at \(time(nil))\n"
                _ = head.withCString { write(CrashLog.fd, $0, strlen($0)) }
                var frames = [UnsafeMutableRawPointer?](repeating: nil, count: 64)
                let n = backtrace(&frames, 64)
                backtrace_symbols_fd(&frames, n, CrashLog.fd)
                signal(s, SIG_DFL); raise(s)
            }
        }
    }
}

/// The Genesis wordmark, tinted to the current ink color so it works in light and dark.
struct GenesisWordmark: View {
    static let image: NSImage? = {
        guard let url = Bundle.main.url(forResource: "GenesisWordmark", withExtension: "png"), let img = NSImage(contentsOf: url) else { return nil }
        img.isTemplate = true
        return img
    }()
    var body: some View {
        if let img = GenesisWordmark.image {
            Image(nsImage: img).resizable().interpolation(.high).aspectRatio(contentMode: .fit)
                .foregroundStyle(Theme.ink)
                .accessibilityLabel("Genesis")
        } else {
            Text("Genesis").font(Typeface.headline(15)).lineLimit(1).foregroundStyle(Theme.ink)
        }
    }
}

/// Content background. On macOS 26 it extends beneath the floating glass sidebar
/// (Apple: use backgroundExtensionEffect() to extend content under sidebars).
struct CanvasBackground: View {
    var body: some View {
        if #available(macOS 26.0, *) {
            Theme.canvas.opacity(0.62).ignoresSafeArea().backgroundExtensionEffect()
        } else {
            Theme.canvas.opacity(0.62).ignoresSafeArea()
        }
    }
}
