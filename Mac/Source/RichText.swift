import SwiftUI
import WebKit
import AppKit

/// Inline text with the emphasis contract the engine writes:
/// `backticks` → a Claude-style inline highlight (faint rounded tint + hairline);
///   code-like content renders in SF Mono, ordinary terms stay proportional.
/// **bold** → the action verb. Nothing else is emphasized.
struct InlineText: View {
    var text: String
    var size: CGFloat = 16
    var color: Color = Theme.ink
    /// true → long-form reading text (roomier leading, reading color supplied by caller).
    var serif: Bool = false
    var weight: Font.Weight = .regular
    /// Titles: one line, never wrapping; shrinks slightly, then truncates with the full text on hover.
    var singleLine: Bool = false
    /// Title voice (New York), echoing the wordmark.
    var display: Bool = false

    var body: some View {
        let text = RichLine.build(self.text, size: size, color: color, serif: serif, weight: weight, display: display)
            .textRenderer(ChipRenderer())
        if singleLine {
            text
                .lineLimit(1)
                .minimumScaleFactor(0.82)
                .truncationMode(.tail)
                .help(self.text.replacingOccurrences(of: "`", with: "").replacingOccurrences(of: "**", with: ""))
        } else {
            text
                .lineSpacing(size * (serif ? 0.5 : 0.36))
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// Marks the runs of one highlight; the id groups padding and glyph runs into a single box.
struct ChipAttribute: TextAttribute { var id: Int }

/// Draws ONE compact rounded container per highlight. A highlight can be split into several
/// runs (the padding spaces fall back to another font), so runs are unioned by id per line;
/// vertical metrics come from the widest run (the real glyphs), never from the padding.
struct ChipRenderer: TextRenderer {
    func draw(layout: Text.Layout, in context: inout GraphicsContext) {
        for line in layout {
            var boxes: [Int: (minX: CGFloat, maxX: CGFloat, top: CGFloat, bottom: CGFloat, width: CGFloat)] = [:]
            var order: [Int] = []
            for run in line {
                guard let chip = run[ChipAttribute.self] else { continue }
                let b = run.typographicBounds
                let top = b.rect.minY + b.ascent * 0.06
                let bottom = b.rect.minY + b.ascent + b.descent * 0.75
                if var box = boxes[chip.id] {
                    box.minX = min(box.minX, b.rect.minX); box.maxX = max(box.maxX, b.rect.maxX)
                    if b.rect.width > box.width { box.top = top; box.bottom = bottom; box.width = b.rect.width }
                    boxes[chip.id] = box
                } else {
                    boxes[chip.id] = (b.rect.minX, b.rect.maxX, top, bottom, b.rect.width); order.append(chip.id)
                }
            }
            for id in order {
                guard let box = boxes[id] else { continue }
                let rect = CGRect(x: box.minX, y: box.top, width: box.maxX - box.minX, height: box.bottom - box.top)
                let path = Path(roundedRect: rect, cornerRadius: min(5, rect.height * 0.26), style: .continuous)
                context.fill(path, with: .color(Theme.chip))
                context.stroke(path, with: .color(Theme.chipBorder), lineWidth: 0.5)
            }
            for run in line { context.draw(run) }
        }
    }
}

enum RichLine {
    enum Token { case plain(String), code(String), bold(String) }

    /// Tiny parser for the two marks the engine uses; anything else stays literal.
    static func tokens(_ s: String) -> [Token] {
        var out: [Token] = []
        var buffer = ""
        var i = s.startIndex
        func flush() { if !buffer.isEmpty { out.append(.plain(buffer)); buffer = "" } }
        while i < s.endIndex {
            if s[i] == "`", let close = s[s.index(after: i)...].firstIndex(of: "`") {
                let inner = String(s[s.index(after: i)..<close])
                if !inner.isEmpty { flush(); out.append(.code(inner)); i = s.index(after: close); continue }
            }
            if s[i...].hasPrefix("**"), let close = s[s.index(i, offsetBy: 2)...].range(of: "**") {
                let inner = String(s[s.index(i, offsetBy: 2)..<close.lowerBound])
                if !inner.isEmpty && !inner.contains("\n") { flush(); out.append(.bold(inner)); i = close.upperBound; continue }
            }
            buffer.append(s[i]); i = s.index(after: i)
        }
        flush()
        return out
    }

    /// Code, identifiers and expressions get SF Mono; plain terminology ("base case",
    /// "pp. 4–5", "Problem 4(b)", "Dynamic Memory Allocation.pdf") stays proportional.
    static func looksLikeCode(_ t: String) -> Bool {
        if t.range(of: #"[(){}\[\];=<>*&|^%#]|->|::|\+\+|--|!="#, options: .regularExpression) != nil {
            // "Problem 4(b)" and "p. 21 (top)" read as labels, not code.
            if t.range(of: #"^(Problem|Question|Exercise|Part|Q|p\.|pp\.)\s"#, options: [.regularExpression, .caseInsensitive]) != nil { return false }
            return true
        }
        if t.contains(" ") { return false }
        if t.range(of: #"^[a-z]+[A-Z]\w*$"#, options: .regularExpression) != nil { return true }   // camelCase
        if t.range(of: #"^\w+_\w+$"#, options: .regularExpression) != nil { return true }          // snake_case
        if t.range(of: #"^[A-Z][a-z]+[A-Z]\w*$"#, options: .regularExpression) != nil { return true } // PascalCase
        if t.range(of: #"^(int|char|void|NULL|null|true|false|malloc|free|struct|class|new|this|return)$"#, options: .regularExpression) != nil { return true }
        if t.range(of: #"^\w+\.(c|h|java|py|txt)$"#, options: .regularExpression) != nil { return true }
        return false
    }

    static func build(_ s: String, size: CGFloat, color: Color, serif: Bool, weight: Font.Weight = .regular, display: Bool = false) -> Text {
        let base = display ? Typeface.display(size, weight) : Typeface.sans(size, weight)
        let strong = display ? Typeface.display(size) : Typeface.sans(size, .semibold)
        var result = Text(verbatim: "")
        var chipID = 0
        for token in tokens(s) {
            switch token {
            case .plain(let t):
                result = result + Text(verbatim: t).font(base).foregroundStyle(color)
            case .bold(let t):
                result = result + Text(verbatim: t).font(strong).foregroundStyle(serif ? color : Theme.ink)
            case .code(let t):
                // Narrow no-break spaces pad the highlight and can't wrap away from the word.
                // Terms use SF Pro (a calm contrast inside New York prose); code uses SF Mono.
                chipID += 1
                let font = looksLikeCode(t) ? Typeface.mono(size * (display ? 0.66 : 0.86)) : Typeface.sans(size * (display ? 0.74 : 0.94), display ? .medium : .regular)
                result = result + Text(verbatim: "\u{202F}" + t + "\u{202F}")
                    .font(font)
                    .foregroundStyle(Theme.chipText)
                    .customAttribute(ChipAttribute(id: chipID))
            }
        }
        return result
    }
}

/// Renders paragraph / code / displayMath blocks.
struct Blocks: View {
    var blocks: [PromptBlock]
    var size: CGFloat = 16
    /// Educational prose reads in New York; pass false for conversational AI text.
    var serif: Bool = true

    var body: some View {
        VStack(alignment: .leading, spacing: serif ? 16 : 12) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                switch block.kind {
                case "code":
                    CodeBlock(code: block.text, language: block.language ?? "")
                case "displayMath":
                    MathView(blocks: [block])
                default:
                    if block.text.contains("$") {
                        MathView(blocks: [block])
                    } else {
                        InlineText(text: block.text, size: size, color: serif ? Theme.reading : Theme.ink, serif: serif)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct CodeBlock: View {
    var code: String
    var language: String
    @State private var copied = false

    static let keywords = #"\b(?:int|void|char|double|float|long|short|unsigned|struct|typedef|return|if|else|while|for|do|switch|case|break|continue|class|extends|implements|interface|abstract|public|private|protected|static|final|new|this|super|null|NULL|true|false|boolean|String|import|package|throws|throw|try|catch|sizeof|const|enum)\b"#

    var highlighted: AttributedString {
        var a = AttributedString(code)
        a.foregroundColor = Theme.ink
        let ns = code as NSString
        func paint(_ pattern: String, _ color: Color) {
            guard let re = try? NSRegularExpression(pattern: pattern) else { return }
            for m in re.matches(in: code, range: NSRange(location: 0, length: ns.length)) {
                if let r = Range(m.range, in: code), let ar = Range(r, in: a) { a[ar].foregroundColor = color }
            }
        }
        paint(CodeBlock.keywords, Theme.ink.opacity(0.62))
        paint(#"\b\d+(?:\.\d+)?\b"#, Theme.success)
        paint(#""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])'"#, Theme.secondary)
        paint(#"//[^\n]*|/\*[\s\S]*?\*/"#, Theme.tertiary)
        return a
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(language.isEmpty ? "Code" : language.capitalized)
                    .font(Typeface.sans(11, .medium)).foregroundStyle(Theme.tertiary)
                Spacer()
                Button(copied ? "Copied" : "Copy") {
                    NSPasteboard.general.clearContents(); NSPasteboard.general.setString(code, forType: .string); copied = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { copied = false }
                }
                .buttonStyle(QuietButtonStyle())
            }
            .padding(.horizontal, 14).padding(.top, 8)
            ScrollView(.horizontal, showsIndicators: false) {
                Text(highlighted)
                    .font(Typeface.mono(13.5))
                    .lineSpacing(5)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: true, vertical: true)
                    .padding(.horizontal, 16).padding(.bottom, 14).padding(.top, 4)
            }
        }
        .background(Theme.well, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Theme.borderStrong, lineWidth: 1))
    }
}

/// KaTeX in a transparent web view, sized to its content.
struct MathView: View {
    var blocks: [PromptBlock]
    @State private var height: CGFloat = 30
    var body: some View {
        MathWeb(blocks: blocks, height: $height)
            .frame(height: height)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct MathWeb: NSViewRepresentable {
    var blocks: [PromptBlock]
    @Binding var height: CGFloat

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: "size")
        let web = NoScrollWebView(frame: .zero, configuration: config)
        web.setValue(false, forKey: "drawsBackground")
        web.navigationDelegate = context.coordinator
        if let folder = Bundle.main.resourceURL?.appendingPathComponent("Math"), FileManager.default.fileExists(atPath: folder.appendingPathComponent("school.html").path) {
            web.loadFileURL(folder.appendingPathComponent("school.html"), allowingReadAccessTo: folder)
        }
        context.coordinator.web = web
        return web
    }

    func updateNSView(_ web: WKWebView, context: Context) {
        context.coordinator.parent = self
        context.coordinator.push()
    }

    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        var parent: MathWeb
        weak var web: WKWebView?
        var loaded = false
        var lastPayload = ""
        init(_ parent: MathWeb) { self.parent = parent }

        func push() {
            guard loaded, let web else { return }
            let payload = ["blocks": parent.blocks.map { ["kind": $0.kind, "text": $0.text] }]
            guard let data = try? JSONSerialization.data(withJSONObject: payload), let json = String(data: data, encoding: .utf8), json != lastPayload else { return }
            lastPayload = json
            web.evaluateJavaScript("render(\(json))", completionHandler: nil)
        }
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { loaded = true; push() }
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            decisionHandler(action.request.url?.isFileURL == true ? .allow : .cancel)
        }
        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            if let h = message.body as? Double { DispatchQueue.main.async { self.parent.height = max(24, CGFloat(h)) } }
            else if let h = message.body as? Int { DispatchQueue.main.async { self.parent.height = max(24, CGFloat(h)) } }
        }
    }
}

final class NoScrollWebView: WKWebView {
    override func scrollWheel(with event: NSEvent) { nextResponder?.scrollWheel(with: event) }
}
