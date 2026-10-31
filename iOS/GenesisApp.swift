import SwiftUI
import CoreText

@main
struct GenesisApp: App {
    @State private var inbox = Inbox()
    @Environment(\.scenePhase) private var phase

    init() { Fonts.register() }

    var body: some Scene {
        WindowGroup {
            TellView()
                .environment(inbox)
                .preferredColorScheme(.dark)
                .onChange(of: phase) { _, now in if now == .active { inbox.refresh() } }
                .onOpenURL { inbox.handle($0) }
        }
    }
}

/// Instrument Serif — the Genesis wordmark's typeface (OFL, Google Fonts).
enum Fonts {
    static func register() {
        // Xcode places processed resources at the app bundle root for app packages.
        guard let url = Bundle.main.url(forResource: "InstrumentSerif-Regular", withExtension: "ttf") else { return }
        CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
    }
    static func title(_ size: CGFloat) -> Font {
        UIFont(name: "InstrumentSerif-Regular", size: size) != nil ? .custom("InstrumentSerif-Regular", fixedSize: size) : .system(size: size, design: .serif)
    }
    static func label(_ size: CGFloat = 11) -> Font { .system(size: size, weight: .medium, design: .monospaced) }
}

enum Palette {
    static let ink = Color(white: 0.93)
    static let secondary = Color(white: 0.62)
    static let tertiary = Color(white: 0.45)
    /// The orb's chromatic edge.
    static let prism: [Color] = [Color(red: 0.49, green: 0.65, blue: 1.0), Color(red: 0.74, green: 0.92, blue: 1.0),
                                 Color(red: 1.0, green: 0.95, blue: 0.79), Color(red: 1.0, green: 0.70, blue: 0.49),
                                 Color(red: 0.79, green: 0.61, blue: 1.0)]
}
