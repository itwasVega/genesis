import SwiftUI
import AppKit
import UniformTypeIdentifiers

// MARK: - The all-in-one answer box
//
// One box for every way you answer: type in it, drop a file on it (a PDF or screenshot of your
// iPad notes, a photo of your paper), or use the paperclip to choose a file or take one straight
// from your iPhone or iPad (Continuity Camera: Take Photo, Scan Documents, Add Sketch). Pages show
// inside the box, and checking happens from the box too.

struct AnswerComposer: View {
    @EnvironmentObject var model: AppModel
    var task: StudyTask
    @Binding var text: String
    @State private var dropTargeted = false

    private var id: String { task.exerciseID }
    private var shape: RoundedRectangle { RoundedRectangle(cornerRadius: 18, style: .continuous) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            AnswerInput(answerType: task.answer_type ?? "short_answer", language: task.language, text: $text, bare: true) { model.submit(task) }
            if let pages = model.attachments[id], !pages.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) { ForEach(pages, id: \.self) { ComposerPage(path: $0, id: id) } }
                        .padding(.horizontal, 14).padding(.vertical, 8)
                }
                .transition(.opacity.combined(with: .move(edge: .bottom)))
            }
            Divider().opacity(0.35).padding(.horizontal, 12)
            HStack(spacing: 10) {
                AttachMenuButton { urls in addFiles(urls) }
                    .frame(width: 96, height: 26)
                    .help("Choose a file, or take a photo, scan or sketch from your iPhone or iPad")
                Text(dropTargeted ? "Let go to add it" : "Type, drop a file, or attach your notes")
                    .font(Typeface.sans(11.5)).foregroundStyle(dropTargeted ? Theme.focus : Theme.tertiary)
                    .lineLimit(1)
                Spacer(minLength: 8)
                Button { model.submit(task) } label: {
                    HStack(spacing: 6) {
                        Text(model.feedback[id] == nil ? "Check" : "Check again")
                        Image(systemName: "arrow.up").font(.system(size: 11, weight: .bold))
                    }
                    .font(Typeface.sans(12.5, .medium))
                    .foregroundStyle(model.canSubmit(id) ? Color.white : Theme.tertiary)
                    .padding(.horizontal, 12).padding(.vertical, 6)
                    .background(Capsule().fill(model.canSubmit(id) ? Theme.focus : Theme.well))
                }
                .buttonStyle(.plain)
                .disabled(!model.canSubmit(id) || model.grading.contains(id))
                .help("Check your answer (⌘↩)")
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
        }
        .background(Theme.raised, in: shape)
        .overlay(shape.strokeBorder(dropTargeted ? Theme.focus : Theme.borderStrong, style: StrokeStyle(lineWidth: dropTargeted ? 1.5 : 1, dash: dropTargeted ? [6, 4] : [])))
        .background(dropTargeted ? Theme.focus.opacity(0.05) : .clear, in: shape)
        .animation(.easeOut(duration: 0.15), value: dropTargeted)
        .animation(.spring(response: 0.35, dampingFraction: 0.85), value: model.attachments[id]?.count ?? 0)
        .onDrop(of: [.fileURL, .image, .pdf], isTargeted: $dropTargeted) { providers in
            PageDrop.load(providers) { urls in addFiles(urls) }
            return true
        }
    }

    /// Pages (PDF, images) attach to the answer; text files are typed into the box for you.
    private func addFiles(_ urls: [URL]) {
        var pages: [URL] = []
        for url in urls {
            let type = UTType(filenameExtension: url.pathExtension.lowercased())
            if let type, type.conforms(to: .plainText) || type.conforms(to: .rtf) || ["md", "markdown", "tex"].contains(url.pathExtension.lowercased()) {
                let body: String? = type.conforms(to: .rtf)
                    ? (try? NSAttributedString(url: url, options: [:], documentAttributes: nil))?.string
                    : try? String(contentsOf: url, encoding: .utf8)
                if let body, !body.isEmpty { text += (text.isEmpty ? "" : "\n") + body }
            } else {
                pages.append(url)
            }
        }
        if !pages.isEmpty { model.addPages(pages, to: id) }
        Companion.shared.noteActivity()
    }
}

/// A page inside the box: click to open, × to remove.
private struct ComposerPage: View {
    @EnvironmentObject var model: AppModel
    var path: String
    var id: String
    var body: some View {
        Button { NSWorkspace.shared.open(URL(fileURLWithPath: path)) } label: {
            Group { if let img = NSImage(contentsOfFile: path) { Image(nsImage: img).resizable().scaledToFill() } else { Theme.well } }
                .frame(width: 52, height: 68).clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 7, style: .continuous).strokeBorder(Theme.ring, lineWidth: 1))
        }
        .buttonStyle(.plain).help("Open this page")
        .overlay(alignment: .topTrailing) {
            Button { model.removePage(path, from: id) } label: {
                Image(systemName: "xmark").font(.system(size: 7, weight: .bold)).foregroundStyle(.white)
                    .frame(width: 16, height: 16).background(Color.black.opacity(0.72), in: Circle())
            }
            .buttonStyle(.plain).offset(x: 5, y: -5).help("Remove this page")
        }
    }
}

/// The paperclip. Its menu: choose a file, or import straight from a nearby iPhone or iPad
/// (Take Photo, Scan Documents, Add Sketch). The last one is AppKit's own Continuity Camera item,
/// so it lists whatever devices are signed in to the same Apple Account.
struct AttachMenuButton: NSViewRepresentable {
    var onFiles: ([URL]) -> Void
    func makeNSView(context: Context) -> AttachNSButton {
        let b = AttachNSButton()
        b.onFiles = onFiles
        return b
    }
    func updateNSView(_ b: AttachNSButton, context: Context) { b.onFiles = onFiles }
}

final class AttachNSButton: NSButton, NSServicesMenuRequestor {
    var onFiles: ([URL]) -> Void = { _ in }

    init() {
        super.init(frame: .zero)
        isBordered = false
        bezelStyle = .inline
        image = NSImage(systemSymbolName: "paperclip", accessibilityDescription: "Attach")
        imagePosition = .imageLeading
        attributedTitle = NSAttributedString(string: " Attach", attributes: [.font: NSFont.systemFont(ofSize: 12, weight: .medium), .foregroundColor: NSColor.secondaryLabelColor])
        contentTintColor = .secondaryLabelColor
        target = self; action = #selector(showMenu)
        setAccessibilityLabel("Attach a file")
    }
    required init?(coder: NSCoder) { fatalError() }

    override var acceptsFirstResponder: Bool { true }

    @objc private func showMenu() {
        window?.makeFirstResponder(self)   // the Continuity Camera item looks for a requestor from here
        let menu = NSMenu()
        let choose = NSMenuItem(title: "Choose a file…", action: #selector(chooseFile), keyEquivalent: "")
        choose.target = self
        menu.addItem(choose)
        menu.addItem(.separator())
        let device = NSMenuItem(title: "Import from iPhone or iPad", action: nil, keyEquivalent: "")
        device.identifier = NSMenuItem.importFromDeviceIdentifier
        menu.addItem(device)
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: bounds.height + 4), in: self)
    }

    @objc private func chooseFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image, .pdf, .plainText, .rtf]
        panel.allowsMultipleSelection = true; panel.canChooseDirectories = false
        panel.message = "Choose your notes: a PDF or screenshot from your iPad, a photo of your paper, or a text file"
        guard panel.runModal() == .OK else { return }
        onFiles(panel.urls)
    }

    // Continuity Camera hands the photo, scan or sketch back through the services pasteboard.
    override func validRequestor(forSendType sendType: NSPasteboard.PasteboardType?, returnType: NSPasteboard.PasteboardType?) -> Any? {
        if let returnType, returnType == .pdf || returnType == .tiff || returnType == .png || NSImage.imageTypes.contains(returnType.rawValue) { return self }
        return super.validRequestor(forSendType: sendType, returnType: returnType)
    }
    func writeSelection(to pboard: NSPasteboard, types: [NSPasteboard.PasteboardType]) -> Bool { false }
    func readSelection(from pboard: NSPasteboard) -> Bool {
        let tmp = FileManager.default.temporaryDirectory
        if let pdf = pboard.data(forType: .pdf) {
            let url = tmp.appendingPathComponent(UUID().uuidString + ".pdf")
            guard (try? pdf.write(to: url)) != nil else { return false }
            onFiles([url]); return true
        }
        if let image = NSImage(pasteboard: pboard), let tiff = image.tiffRepresentation,
           let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]) {
            let url = tmp.appendingPathComponent(UUID().uuidString + ".png")
            guard (try? png.write(to: url)) != nil else { return false }
            onFiles([url]); return true
        }
        return false
    }
}
