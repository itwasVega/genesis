import Foundation
import AppKit
import PDFKit
import Vision

// Native, read-only PDF extraction; no third-party PDF engine is redistributed.
func extract(_ path: String, ocr: Bool) throws -> [String: Any] {
    guard let document = PDFDocument(url: URL(fileURLWithPath: path)), !document.isEncrypted,
          document.pageCount > 0, document.pageCount <= 250 else {
        throw NSError(domain: "GenesisPDF", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid, encrypted, empty, or oversized PDF"])
    }
    var pages: [String] = []
    for i in 0..<document.pageCount {
        guard let page = document.page(at: i) else { throw CocoaError(.fileReadCorruptFile) }
        if ocr {
            let image = page.thumbnail(of: NSSize(width: 1600, height: 2000), for: .mediaBox)
            var rect = CGRect(origin: .zero, size: image.size)
            guard let cg = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else { throw CocoaError(.fileReadCorruptFile) }
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            try VNImageRequestHandler(cgImage: cg, options: [:]).perform([request])
            pages.append((request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n"))
        } else { pages.append(String((page.string ?? "").prefix(100_000))) }
    }
    return ["pages": pages, "page_count": document.pageCount]
}

@main struct GenesisPDFMain {
static func main() {

do {
    let args = CommandLine.arguments
    guard args.count == 2, ["text", "ocr"].contains(args[1]) else { throw CocoaError(.validationMissingMandatoryProperty) }
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard data.count < 1_000_000, let paths = try JSONSerialization.jsonObject(with: data) as? [String], paths.count <= 40 else { throw CocoaError(.fileReadCorruptFile) }
    var result: [String: Any] = [:]
    for path in paths {
        do { result[path] = try extract(path, ocr: args[1] == "ocr") }
        catch { result[path] = ["error": error.localizedDescription] }
    }
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: result))
} catch {
    FileHandle.standardError.write(Data("PDF extraction failed.\n".utf8)); exit(1)
}

}
}
