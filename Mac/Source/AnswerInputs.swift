import SwiftUI
import AppKit

/// Chooses an input from what the student must produce, not from whether the
/// prompt contains code.
struct AnswerInput: View {
    var answerType: String
    var language: String?
    @Binding var text: String
    var bare = false              // inside the all-in-one answer box, which draws the frame
    var onSubmit: () -> Void

    var body: some View {
        switch answerType {
        case "code":
            VStack(alignment: .leading, spacing: 6) {
                Text((language?.capitalized ?? "Code") + Theme.sep + "Tab indents, ⌘↩ checks")
                    .font(Typeface.sans(11)).foregroundStyle(Theme.tertiary)
                CodeEditor(text: $text, onSubmit: onSubmit)
                    .frame(minHeight: 220, idealHeight: 300)
                    .background(Theme.well, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Theme.borderStrong, lineWidth: 1).opacity(bare ? 0 : 1))
            }
            .padding(bare ? 8 : 0)
        case "memory_trace", "code_trace", "table":
            LongAnswer(text: $text, placeholder: answerType == "table" ? "One row per line, columns separated by |" : "line 4: x = 5, p → node A", mono: true, bare: bare, onSubmit: onSubmit)
        case "derivation", "proof", "explanation", "mixed":
            LongAnswer(text: $text, placeholder: answerType == "derivation" ? "Your work, one step per line" : answerType == "proof" ? "1. … because …\n2. … because …" : "Write your answer", mono: false, bare: bare, onSubmit: onSubmit)
        default:
            PillField(text: $text, placeholder: answerType == "numeric" ? "e.g. 7 or -3/4" : "Your answer", bare: bare, onSubmit: onSubmit)
        }
    }
}

/// Pill-shaped input that grows with its text.
struct PillField: View {
    @Binding var text: String
    var placeholder: String
    var bare = false
    var onSubmit: () -> Void
    @FocusState private var focused: Bool
    var body: some View {
        if bare {
            TextField(placeholder, text: $text, axis: .vertical)
                .textFieldStyle(.plain).font(Typeface.sans(15)).lineLimit(1...8)
                .onSubmit(onSubmit)
                .padding(.horizontal, 16).padding(.vertical, 14)
                .background(TextDropPassthrough())
        } else {
        TextField(placeholder, text: $text, axis: .vertical)
            .textFieldStyle(.plain)
            .font(Typeface.sans(14))
            .lineLimit(1...8)
            .focused($focused)
            .onSubmit(onSubmit)
            .padding(.horizontal, 16).padding(.vertical, 10)
            .background(Theme.raised, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(Theme.borderStrong, lineWidth: 1).opacity(focused ? 0 : 1))
            .prismRim(RoundedRectangle(cornerRadius: 18, style: .continuous), active: focused, lineWidth: 1.5)
            .animation(.easeOut(duration: 0.15), value: focused)
        }
    }
}

struct LongAnswer: View {
    @Binding var text: String
    var placeholder: String
    var mono: Bool
    var bare = false
    var onSubmit: () -> Void
    @FocusState private var focused: Bool
    var body: some View {
        ZStack(alignment: .topLeading) {
            if text.isEmpty {
                Text(placeholder).font(mono ? Typeface.mono(14) : Typeface.sans(15)).foregroundStyle(Theme.tertiary)
                    .padding(.horizontal, 17).padding(.vertical, 14).allowsHitTesting(false)
            }
            TextEditor(text: $text)
                .font(mono ? Typeface.mono(14) : Typeface.sans(15))
                .scrollContentBackground(.hidden)
                .focused($focused)
                .padding(.horizontal, 12).padding(.vertical, 10)
                .frame(minHeight: 140)
        }
        .background(bare ? .clear : Theme.raised, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(focused ? Theme.focus : Theme.ring, lineWidth: focused ? 1.5 : 1).opacity(bare ? 0 : 1))
        .background(KeyCatcher(onCommandReturn: onSubmit))
        .background(TextDropPassthrough())
    }
}

/// Makes the SwiftUI text editor ignore dropped files and images (it would paste
/// their file path), so the answer area can attach them as pages instead.
struct TextDropPassthrough: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView { NSView() }
    func updateNSView(_ v: NSView, context: Context) {
        DispatchQueue.main.async {
            var root: NSView? = v
            for _ in 0..<3 { root = root?.superview }
            func visit(_ view: NSView) {
                if let tv = view as? NSTextView { tv.unregisterDraggedTypes(); tv.registerForDraggedTypes([.string]) }
                view.subviews.forEach(visit)
            }
            if let root { visit(root) }
        }
    }
}

/// ⌘↩ anywhere in the editor submits.
struct KeyCatcher: NSViewRepresentable {
    var onCommandReturn: () -> Void
    func makeNSView(context: Context) -> NSView {
        let v = NSView()
        context.coordinator.monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if event.modifierFlags.contains(.command), event.keyCode == 36 { context.coordinator.action(); return nil }
            return event
        }
        return v
    }
    func updateNSView(_ nsView: NSView, context: Context) { context.coordinator.action = onCommandReturn }
    func makeCoordinator() -> Coordinator { Coordinator(onCommandReturn) }
    static func dismantleNSView(_ nsView: NSView, coordinator: Coordinator) { if let m = coordinator.monitor { NSEvent.removeMonitor(m) } }
    final class Coordinator { var action: () -> Void; var monitor: Any?; init(_ a: @escaping () -> Void) { action = a } }
}

/// IDE-like editor: monospace, tab = 4 spaces, auto-indent, no smart quotes.
struct CodeEditor: NSViewRepresentable {
    @Binding var text: String
    var onSubmit: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSTextView.scrollableTextView()
        scroll.drawsBackground = false
        scroll.borderType = .noBorder
        guard let tv = scroll.documentView as? NSTextView else { return scroll }
        tv.delegate = context.coordinator
        tv.font = .monospacedSystemFont(ofSize: 14, weight: .regular)
        tv.textColor = .labelColor
        tv.drawsBackground = false
        tv.isAutomaticQuoteSubstitutionEnabled = false
        tv.isAutomaticDashSubstitutionEnabled = false
        tv.isAutomaticTextReplacementEnabled = false
        tv.isAutomaticSpellingCorrectionEnabled = false
        tv.isContinuousSpellCheckingEnabled = false
        tv.allowsUndo = true
        tv.textContainerInset = NSSize(width: 14, height: 14)
        tv.string = text
        let style = NSMutableParagraphStyle(); style.lineSpacing = 3
        tv.defaultParagraphStyle = style
        tv.typingAttributes = [.font: NSFont.monospacedSystemFont(ofSize: 14, weight: .regular), .foregroundColor: NSColor.labelColor, .paragraphStyle: style]
        tv.unregisterDraggedTypes(); tv.registerForDraggedTypes([.string])   // dropped pages go to the answer area, not in as a file path
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        context.coordinator.parent = self
        if let tv = scroll.documentView as? NSTextView, tv.string != text { tv.string = text }
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: CodeEditor
        init(_ p: CodeEditor) { parent = p }
        func textDidChange(_ n: Notification) {
            guard let tv = n.object as? NSTextView else { return }
            parent.text = tv.string
        }
        func textView(_ tv: NSTextView, doCommandBy selector: Selector) -> Bool {
            if selector == #selector(NSResponder.insertTab(_:)) { tv.insertText("    ", replacementRange: tv.selectedRange()); return true }
            if selector == #selector(NSResponder.insertNewline(_:)) {
                if NSEvent.modifierFlags.contains(.command) { parent.onSubmit(); return true }
                let s = tv.string as NSString
                let line = s.lineRange(for: NSRange(location: tv.selectedRange().location, length: 0))
                let current = s.substring(with: line)
                var indent = String(current.prefix { $0 == " " || $0 == "\t" })
                if current.trimmingCharacters(in: .whitespacesAndNewlines).hasSuffix("{") { indent += "    " }
                tv.insertText("\n" + indent, replacementRange: tv.selectedRange())
                return true
            }
            return false
        }
    }
}
