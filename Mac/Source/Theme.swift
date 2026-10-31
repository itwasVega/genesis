import SwiftUI
import AppKit
import CoreText

// MARK: - Color tokens (DESIGN.md, without Terracotta/Coral: no chromatic accent)

extension Color {
    /// A color that resolves differently in light and dark appearance.
    /// Translucent tokens that sit correctly on any surface (canvas, card, raised).
    init(light: UInt32, lightAlpha: CGFloat, dark: UInt32, darkAlpha: CGFloat) {
        self.init(nsColor: NSColor(name: nil) { appearance in
            let isDark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            return isDark ? NSColor(hex: dark, alpha: darkAlpha) : NSColor(hex: light, alpha: lightAlpha)
        })
    }
    init(light: UInt32, dark: UInt32) {
        self.init(nsColor: NSColor(name: nil) { appearance in
            let isDark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            return NSColor(hex: isDark ? dark : light)
        })
    }
}

extension NSColor {
    convenience init(hex: UInt32, alpha: CGFloat = 1) {
        self.init(srgbRed: CGFloat((hex >> 16) & 0xff) / 255,
                  green: CGFloat((hex >> 8) & 0xff) / 255,
                  blue: CGFloat(hex & 0xff) / 255,
                  alpha: alpha)
    }
}

enum Theme {
    // "Obsidian": cold near-black glass taken from the Genesis orb. Dark is the native mode;
    // light mode is a cool graphite-on-frost mirror of it.
    // Surfaces
    static let canvas = Color(light: 0xF2F2F4, dark: 0x08080A)
    // Content surfaces are translucent so the window's frosted glass reads through them,
    // matching the system glass sidebar.
    static let surface = Color(light: 0xFFFFFF, lightAlpha: 0.55, dark: 0xFFFFFF, darkAlpha: 0.045)
    static let raised = Color(light: 0xFFFFFF, lightAlpha: 0.75, dark: 0xFFFFFF, darkAlpha: 0.075)
    /// Recessed wells for code and inputs: darker than the glass around them.
    static let well = Color(light: 0x0B0B0D, lightAlpha: 0.04, dark: 0x000000, darkAlpha: 0.28)
    static let sand = Color(light: 0x0B0B0D, lightAlpha: 0.06, dark: 0xFFFFFF, darkAlpha: 0.07)   // neutral fill (tags, tracks, hover)
    static let sidebar = Color(light: 0xEBEBEE, dark: 0x050507)
    // Text
    static let ink = Color(light: 0x0B0B0D, dark: 0xEDEDF2)
    /// Long-form reading text: a touch softer than ink so it doesn't glare in dark mode.
    static let reading = Color(light: 0x1A1A1F, dark: 0xD2D2DA)
    static let secondary = Color(light: 0x52525B, dark: 0xA0A0AB)
    static let tertiary = Color(light: 0x6E6E78, dark: 0x7C7C87)
    // Lines and rings (translucent so they sit on any surface)
    static let border = Color(light: 0x0B0B0D, lightAlpha: 0.08, dark: 0xFFFFFF, darkAlpha: 0.065)
    static let borderStrong = Color(light: 0x0B0B0D, lightAlpha: 0.12, dark: 0xFFFFFF, darkAlpha: 0.10)
    static let ring = Color(light: 0x0B0B0D, lightAlpha: 0.16, dark: 0xFFFFFF, darkAlpha: 0.14)
    static let ringDeep = Color(light: 0x0B0B0D, lightAlpha: 0.26, dark: 0xFFFFFF, darkAlpha: 0.24)
    // Inline highlight (Claude-style): a faint tint plus hairline, never a solid block.
    static let chip = Color(light: 0x0B0B0D, lightAlpha: 0.055, dark: 0xFFFFFF, darkAlpha: 0.07)
    static let chipBorder = Color(light: 0x0B0B0D, lightAlpha: 0.09, dark: 0xFFFFFF, darkAlpha: 0.10)
    static let chipText = Color(light: 0x1A1A1F, dark: 0xE6E6EE)
    // Semantic (muted; the only flat colors that carry meaning)
    static let success = Color(light: 0x2E7A5C, dark: 0x8ED6B6)
    static let error = Color(light: 0xB23A34, dark: 0xF08C86)
    static let focus = Color(light: 0x3B7BE8, dark: 0x8FB4FF)
    // Primary action: inverted ink, no hue
    static let primaryFill = Color(light: 0x0B0B0D, dark: 0xEDEDF2)
    static let primaryText = Color(light: 0xF2F2F4, dark: 0x08080A)
    // Shimmer band on in-progress labels
    static let shimmer = Color(light: 0x0B0B0D, dark: 0xFFFFFF)

    /// The orb's chromatic edge: cool blue → ice → pale gold → ember → violet. Used only as a
    /// thin line (progress, selection, the active marker), never as a fill behind text.
    static let prismColors: [Color] = [Color(nsColor: NSColor(hex: 0x7EA6FF)), Color(nsColor: NSColor(hex: 0xBDEBFF)),
                                       Color(nsColor: NSColor(hex: 0xFFF1C9)), Color(nsColor: NSColor(hex: 0xFFB27E)),
                                       Color(nsColor: NSColor(hex: 0xC99BFF))]
    /// Tint that makes primary glass read brighter than secondary glass.
    static let glassTint = Color(light: 0xFFFFFF, lightAlpha: 0.55, dark: 0xFFFFFF, darkAlpha: 0.12)
    static var prism: LinearGradient { LinearGradient(colors: prismColors, startPoint: .leading, endPoint: .trailing) }

    static func courseLabel(_ id: String) -> String {
        switch id {
        case "COP3330": return "Java"
        case "COP3502C": return "CS1"
        case "MAC2311C": return "Calculus"
        case "COT3100C": return "Discrete"
        case "CIS3360": return "Security"
        default: return id
        }
    }
}

// MARK: - Type

/// Genesis type system — three voices:
/// - Title voice: Instrument Serif (Rodrigo Fuenzalida & Jordan Egstad, OFL, via Google Fonts),
///   the typeface of the Genesis wordmark. Page titles, task titles, card titles. Always one line.
/// - Instrument voice: SF Mono, uppercase, widely tracked — eyebrows, metadata, counters.
/// - Text voice: SF Pro Text — interface, steps, lessons, AI feedback.
enum Typeface {
    /// Registers the bundled Instrument Serif files for this process.
    static let registered: Void = {
        guard let folder = Bundle.main.resourceURL?.appendingPathComponent("Fonts"),
              let files = try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil) else { return }
        for file in files where ["ttf", "otf"].contains(file.pathExtension.lowercased()) {
            CTFontManagerRegisterFontsForURL(file as CFURL, .process, nil)
        }
    }()

    /// Instrument Serif at a size; New York if the font file is missing.
    static func title(_ size: CGFloat, italic: Bool = false) -> Font {
        _ = registered
        let name = italic ? "InstrumentSerif-Italic" : "InstrumentSerif-Regular"
        return NSFont(name: name, size: size) != nil ? .custom(name, fixedSize: size) : .system(size: size, design: .serif)
    }

    /// Page titles ("Begin.", "Progress").
    static func largeTitle(_ size: CGFloat = 36) -> Font { title(size) }
    /// Task, card and section titles (Instrument Serif runs narrow, so it is set a touch larger). Pair with `.lineLimit(1)`.
    static func headline(_ size: CGFloat = 16) -> Font { title((size * 1.15).rounded()) }
    /// Title voice for inline titles with highlights (Instrument Serif has a single weight).
    static func display(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font { title((size * 1.12).rounded()) }
    /// Legacy name for headline.
    static func serif(_ size: CGFloat) -> Font { headline(size) }
    /// Long-form reading text (lessons, problems, worked examples).
    static func serifText(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font { .system(size: size, weight: weight) }
    /// Interface text.
    static func sans(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font { .system(size: size, weight: weight) }
    /// Uppercase instrument labels and metadata.
    static func label(_ size: CGFloat = 10.5, _ weight: Font.Weight = .medium) -> Font { .system(size: size, weight: weight, design: .monospaced) }
    /// Code and exact identifiers.
    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font { .system(size: size, weight: weight, design: .monospaced) }
    static func nsSans(_ size: CGFloat) -> NSFont { .systemFont(ofSize: size) }
}

// MARK: - Liquid Glass

extension View {
    /// Liquid Glass on macOS 26+, a frosted material before that.
    @ViewBuilder
    func genesisGlass<S: Shape>(_ shape: S, tint: Color? = nil, interactive: Bool = false) -> some View {
        if #available(macOS 26.0, *) {
            let base: Glass = tint.map { Glass.regular.tint($0) } ?? .regular
            self.glassEffect(interactive ? base.interactive() : base, in: shape)
        } else {
            self.background(.ultraThinMaterial, in: shape)
                .background(tint ?? .clear, in: shape)
        }
    }

    /// The orb's spectrum as a slowly turning rim, shown while the pointer is over a control.
    func prismRim<S: InsettableShape>(_ shape: S, active: Bool, lineWidth: CGFloat = 1) -> some View {
        overlay { PrismRim(shape: shape, active: active, lineWidth: lineWidth) }
    }
}

struct PrismRim<S: InsettableShape>: View {
    var shape: S
    var active: Bool
    var lineWidth: CGFloat = 1
    @Environment(\.accessibilityReduceMotion) private var reduce
    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 60, paused: !active || reduce)) { context in
            let angle = reduce ? 0 : context.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 6) / 6 * 360
            shape.strokeBorder(AngularGradient(colors: Theme.prismColors + [Theme.prismColors[0]], center: .center, angle: .degrees(angle)),
                               lineWidth: lineWidth)
        }
        .opacity(active ? 1 : 0)
        .animation(.easeOut(duration: 0.18), value: active)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

// MARK: - Buttons

extension View {
    /// Primary action. macOS 26+: the system Liquid Glass button style, tinted slightly brighter
    /// than secondary actions (Apple: use the new button styles instead of custom glass effects).
    /// Hover lights the rim with the orb's spectrum.
    @ViewBuilder
    func primaryAction() -> some View {
        if #available(macOS 26.0, *) {
            self.buttonStyle(.glass(.regular.tint(Theme.glassTint))).buttonBorderShape(.capsule).modifier(HoverRim())
        } else {
            self.buttonStyle(PrimaryButtonStyle())
        }
    }

    /// Secondary action: the system Liquid Glass button style, untinted.
    @ViewBuilder
    func secondaryAction() -> some View {
        if #available(macOS 26.0, *) {
            self.buttonStyle(.glass).buttonBorderShape(.capsule).modifier(HoverRim())
        } else {
            self.buttonStyle(SecondaryButtonStyle())
        }
    }
}

/// The prism rim around a system glass button while the pointer is over it.
struct HoverRim: ViewModifier {
    @State private var hover = false
    @Environment(\.isEnabled) private var enabled
    func body(content: Content) -> some View {
        content
            .prismRim(Capsule(), active: hover && enabled, lineWidth: 1.5)
            .onHover { hover = $0 }
    }
}

/// Pre-macOS 26 fallback for primaryAction().
struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View { GlassButtonBody(configuration: configuration, prominent: true) }
}

/// Pre-macOS 26 fallback for secondaryAction().
struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View { GlassButtonBody(configuration: configuration, prominent: false) }
}

private struct GlassButtonBody: View {
    let configuration: ButtonStyleConfiguration
    let prominent: Bool
    @Environment(\.isEnabled) private var enabled
    @State private var hover = false
    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 9, style: .continuous)
        configuration.label
            .font(Typeface.sans(13, prominent ? .semibold : .medium))
            .foregroundStyle(Theme.ink.opacity(enabled ? 1 : 0.4))
            .padding(.horizontal, prominent ? 16 : 14).padding(.vertical, 8)
            .frame(minHeight: prominent ? 36 : 32)
            .contentShape(shape)
            .background(.ultraThinMaterial, in: shape)
            .background(prominent ? Theme.glassTint : .clear, in: shape)
            .overlay(shape.strokeBorder(Theme.borderStrong, lineWidth: 1).opacity(hover && enabled ? 0 : 1))
            .prismRim(shape, active: hover && enabled)
            // Hover is tracked on a clear layer above the glass: the glass layer itself
            // doesn't forward pointer tracking to views beneath it.
            .overlay { Color.clear.contentShape(shape).onContinuousHover { phase in
                if case .active = phase { if !hover { hover = true } } else { hover = false }
            } }
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.spring(response: 0.25, dampingFraction: 0.7), value: configuration.isPressed)
    }
}

struct QuietButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View { QuietButtonBody(configuration: configuration) }
}

private struct QuietButtonBody: View {
    let configuration: ButtonStyleConfiguration
    @State private var hover = false
    var body: some View {
        configuration.label
            .font(Typeface.sans(13))
            .foregroundStyle(hover ? Theme.ink : Theme.secondary)
            .padding(.horizontal, 8).padding(.vertical, 5)
            .background(hover ? Theme.sand.opacity(0.6) : .clear, in: RoundedRectangle(cornerRadius: 7, style: .continuous))
            .opacity(configuration.isPressed ? 0.7 : 1)
            .onHover { hover = $0 }
            .animation(.easeOut(duration: 0.12), value: hover)
            .contentShape(Rectangle())
    }
}

// MARK: - Surfaces

struct Card: ViewModifier {
    var padding: CGFloat = 20
    var radius: CGFloat = 16
    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .shadow(color: .black.opacity(0.18), radius: 18, x: 0, y: 8)
            .overlay(
                // Glass edge: a hairline that is brighter at the top, like light on the orb's rim.
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(LinearGradient(colors: [Theme.borderStrong, Theme.border, Theme.border], startPoint: .top, endPoint: .bottom), lineWidth: 1)
            )
    }
}

extension View {
    func card(padding: CGFloat = 20, radius: CGFloat = 16) -> some View { modifier(Card(padding: padding, radius: radius)) }

    /// Claude-style moving highlight across an in-progress label.
    func shimmer(_ active: Bool = true) -> some View { modifier(Shimmer(active: active)) }
}

// MARK: - Motion

struct Shimmer: ViewModifier {
    var active: Bool
    @Environment(\.accessibilityReduceMotion) private var reduce
    @ViewBuilder
    func body(content: Content) -> some View {
        if !active || reduce {
            content
        } else {
            content
                .foregroundStyle(Theme.tertiary)
                .overlay {
                    TimelineView(.animation(minimumInterval: 1 / 60)) { context in
                        let t = context.date.timeIntervalSinceReferenceDate
                        let phase = CGFloat((t.truncatingRemainder(dividingBy: 1.8)) / 1.8)
                        GeometryReader { geo in
                            let w = max(geo.size.width, 1)
                            LinearGradient(colors: [.clear, Theme.shimmer.opacity(0.95), .clear], startPoint: .leading, endPoint: .trailing)
                                .frame(width: w * 0.45)
                                .offset(x: -w * 0.45 + phase * (w * 1.45))
                        }
                    }
                    .mask(content)
                    .allowsHitTesting(false)
                }
        }
    }
}

/// Determinate bar that animates between values; indeterminate when value is nil.
struct ProgressLine: View {
    var value: Double?
    var height: CGFloat = 2
    @Environment(\.accessibilityReduceMotion) private var reduce
    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Theme.sand)
                if let value {
                    Capsule()
                        .fill(Theme.prism)
                        .frame(width: max(height, geo.size.width * CGFloat(min(max(value, 0), 1))))
                        .animation(.spring(response: 0.6, dampingFraction: 0.85), value: value)
                } else if reduce {
                    Capsule().fill(Theme.ink.opacity(0.4)).frame(width: geo.size.width * 0.3)
                } else {
                    TimelineView(.animation) { context in
                        let t = context.date.timeIntervalSinceReferenceDate
                        let p = CGFloat(t.truncatingRemainder(dividingBy: 1.4) / 1.4)
                        Capsule().fill(Theme.prism)
                            .frame(width: geo.size.width * 0.28)
                            .offset(x: -geo.size.width * 0.28 + p * geo.size.width * 1.28)
                    }
                }
            }
            .clipShape(Capsule())
        }
        .frame(height: height)
        .accessibilityElement()
        .accessibilityLabel("Progress")
        .accessibilityValue(value.map { "\(Int($0 * 100)) percent" } ?? "In progress")
    }
}

// MARK: - Marks (precise, instrument-like; names kept from the old hand-drawn set)

private func poly(_ points: [CGPoint], in rect: CGRect) -> Path {
    var path = Path()
    guard let first = points.first else { return path }
    func map(_ p: CGPoint) -> CGPoint { CGPoint(x: rect.minX + p.x * rect.width, y: rect.minY + p.y * rect.height) }
    path.move(to: map(first))
    for p in points.dropFirst() { path.addLine(to: map(p)) }
    return path
}

struct SketchCheck: Shape {
    func path(in rect: CGRect) -> Path { poly([CGPoint(x: 0.16, y: 0.54), CGPoint(x: 0.40, y: 0.76), CGPoint(x: 0.86, y: 0.24)], in: rect) }
}

struct SketchCross: Shape {
    func path(in rect: CGRect) -> Path {
        var p = poly([CGPoint(x: 0.24, y: 0.24), CGPoint(x: 0.76, y: 0.76)], in: rect)
        p.addPath(poly([CGPoint(x: 0.76, y: 0.24), CGPoint(x: 0.24, y: 0.76)], in: rect))
        return p
    }
}

struct SketchUnderline: Shape {
    func path(in rect: CGRect) -> Path { poly([CGPoint(x: 0, y: 0.5), CGPoint(x: 1, y: 0.5)], in: rect) }
}

/// Empty-state mark: an orb outline with an inner orbit.
struct SketchPencil: Shape {
    func path(in rect: CGRect) -> Path {
        let r = min(rect.width, rect.height) / 2
        let c = CGPoint(x: rect.midX, y: rect.midY)
        var p = Path(ellipseIn: CGRect(x: c.x - r, y: c.y - r, width: r * 2, height: r * 2))
        p.addArc(center: CGPoint(x: c.x + r * 0.12, y: c.y + r * 0.1), radius: r * 0.62, startAngle: .degrees(200), endAngle: .degrees(20), clockwise: false)
        return p
    }
}

struct SketchScribble: Shape {
    func path(in rect: CGRect) -> Path { poly([CGPoint(x: 0, y: 0.5), CGPoint(x: 1, y: 0.5)], in: rect) }
}

// MARK: - Glyphs (one or two strokes each; 1.2 pt; no fills)

enum Glyph { case today, practice, progress, library, settings, sync, back, forward, arrow, close, search, clock, page, hint, panel, calendar, check }

struct GlyphShape: Shape {
    var glyph: Glyph
    func path(in r: CGRect) -> Path {
        let s = min(r.width, r.height), c = CGPoint(x: r.midX, y: r.midY)
        func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: c.x + (x - 0.5) * s, y: c.y + (y - 0.5) * s) }
        func line(_ a: (CGFloat, CGFloat), _ b: (CGFloat, CGFloat), _ p: inout Path) { p.move(to: pt(a.0, a.1)); p.addLine(to: pt(b.0, b.1)) }
        func ring(_ d: CGFloat, _ p: inout Path) { p.addEllipse(in: CGRect(x: c.x - s * d / 2, y: c.y - s * d / 2, width: s * d, height: s * d)) }
        var p = Path()
        switch glyph {
        case .today: ring(0.84, &p)                                                   // the orb
        case .practice:                                                                // diamond
            p.move(to: pt(0.5, 0.08)); p.addLine(to: pt(0.92, 0.5)); p.addLine(to: pt(0.5, 0.92)); p.addLine(to: pt(0.08, 0.5)); p.closeSubpath()
        case .progress: line((0.12, 0.86), (0.88, 0.14), &p)                           // ascent
        case .library: line((0.1, 0.36), (0.9, 0.36), &p); line((0.1, 0.64), (0.9, 0.64), &p)
        case .settings:                                                                // hexagon
            for i in 0...6 {
                let a = Double(i) * .pi / 3 + .pi / 6
                let q = CGPoint(x: c.x + cos(a) * s * 0.44, y: c.y + sin(a) * s * 0.44)
                i == 0 ? p.move(to: q) : p.addLine(to: q)
            }
        case .sync: p.addArc(center: c, radius: s * 0.4, startAngle: .degrees(-50), endAngle: .degrees(240), clockwise: false)
        case .back: p.move(to: pt(0.62, 0.2)); p.addLine(to: pt(0.32, 0.5)); p.addLine(to: pt(0.62, 0.8))
        case .forward: p.move(to: pt(0.38, 0.2)); p.addLine(to: pt(0.68, 0.5)); p.addLine(to: pt(0.38, 0.8))
        case .arrow: line((0.1, 0.5), (0.9, 0.5), &p); p.move(to: pt(0.62, 0.24)); p.addLine(to: pt(0.9, 0.5)); p.addLine(to: pt(0.62, 0.76))
        case .close: line((0.22, 0.22), (0.78, 0.78), &p); line((0.78, 0.22), (0.22, 0.78), &p)
        case .search: p.addEllipse(in: CGRect(x: pt(0.1, 0.1).x, y: pt(0.1, 0.1).y, width: s * 0.58, height: s * 0.58)); line((0.62, 0.62), (0.9, 0.9), &p)
        case .clock: ring(0.84, &p); line((0.5, 0.26), (0.5, 0.5), &p); line((0.5, 0.5), (0.68, 0.6), &p)
        case .page: p.addRoundedRect(in: CGRect(x: pt(0.2, 0.08).x, y: pt(0.2, 0.08).y, width: s * 0.6, height: s * 0.84), cornerSize: CGSize(width: s * 0.06, height: s * 0.06))
        case .hint: ring(0.5, &p); line((0.5, 0.0), (0.5, 0.12), &p); line((0.5, 0.88), (0.5, 1.0), &p)
        case .panel: p.addRoundedRect(in: CGRect(x: pt(0.06, 0.14).x, y: pt(0.06, 0.14).y, width: s * 0.88, height: s * 0.72), cornerSize: CGSize(width: s * 0.08, height: s * 0.08)); line((0.62, 0.14), (0.62, 0.86), &p)
        case .calendar: p.addRoundedRect(in: CGRect(x: pt(0.08, 0.16).x, y: pt(0.08, 0.16).y, width: s * 0.84, height: s * 0.74), cornerSize: CGSize(width: s * 0.08, height: s * 0.08)); line((0.08, 0.38), (0.92, 0.38), &p)
        case .check: p.move(to: pt(0.16, 0.54)); p.addLine(to: pt(0.4, 0.76)); p.addLine(to: pt(0.86, 0.24))
        }
        return p
    }
}

struct GlyphView: View {
    var glyph: Glyph
    var size: CGFloat = 15
    var body: some View {
        GlyphShape(glyph: glyph)
            .stroke(style: StrokeStyle(lineWidth: 1.2, lineCap: .round, lineJoin: .round))
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

/// Draws a doodle on appear, like a pen stroke.
struct DrawOn<S: Shape>: View {
    var shape: S
    var color: Color = Theme.ink
    var lineWidth: CGFloat = 2.4
    var duration: Double = 0.55
    var delay: Double = 0
    @State private var progress: CGFloat = 0
    @Environment(\.accessibilityReduceMotion) private var reduce
    var body: some View {
        shape.trim(from: 0, to: reduce ? 1 : progress)
            .stroke(color, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round, lineJoin: .round))
            .onAppear {
                guard !reduce else { return }
                progress = 0
                withAnimation(.easeOut(duration: duration).delay(delay)) { progress = 1 }
            }
            .accessibilityHidden(true)
    }
}

/// Waiting state: a faint orbit with a prism arc sweeping around it.
struct ScribbleLoader: View {
    var color: Color = Theme.tertiary
    @Environment(\.accessibilityReduceMotion) private var reduce
    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 60, paused: reduce)) { context in
            let t = context.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1.6) / 1.6
            ZStack {
                Circle().stroke(Theme.border, lineWidth: 1.25)
                Circle().trim(from: 0, to: 0.28)
                    .stroke(AngularGradient(colors: Theme.prismColors, center: .center), style: StrokeStyle(lineWidth: 1.5, lineCap: .round))
                    .rotationEffect(.degrees(reduce ? 0 : t * 360))
            }
            .aspectRatio(1, contentMode: .fit)
        }
        .accessibilityHidden(true)
    }
}

// MARK: - Small shared views

extension Theme {
    /// Separator inside one line of text ("cop3502-midterm.pdf / p. 21").
    /// The previous style was Theme.sep; change this one constant to go back.
    static let sep = "  /  "
}

/// Separator between items in a row: a short vertical hairline.
/// (Previous style: a centered dot — swap the body for `Text("·")` to go back.)
struct SeparatorMark: View {
    var body: some View {
        Rectangle().fill(Theme.borderStrong).frame(width: 1, height: 10).padding(.horizontal, 2).accessibilityHidden(true)
    }
}

extension ISO8601DateFormatter {
    /// "2026-10-28" in the user's time zone.
    static let day: ISO8601DateFormatter = { let f = ISO8601DateFormatter(); f.formatOptions = [.withFullDate]; f.timeZone = .current; return f }()
}


struct Tag: View {
    var text: String
    var body: some View {
        Text(text.uppercased())
            .font(Typeface.label(10))
            .tracking(0.8)
            .foregroundStyle(Theme.secondary)
            .lineLimit(1)
            .padding(.horizontal, 7).padding(.vertical, 3)
            .overlay(RoundedRectangle(cornerRadius: 4, style: .continuous).strokeBorder(Theme.borderStrong, lineWidth: 1))
    }
}

struct SectionTitle: View {
    var text: String
    var body: some View {
        Text(text.uppercased())
            .font(Typeface.label(10.5))
            .tracking(1.4)
            .foregroundStyle(Theme.tertiary)
            .lineLimit(1)
    }
}

func minutesLabel(_ m: Int) -> String {
    let h = m / 60, r = m % 60
    if h == 0 { return "\(r) min" }
    return r == 0 ? "\(h) h" : "\(h) h \(r) min"
}
