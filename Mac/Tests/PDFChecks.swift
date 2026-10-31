import Foundation
import AppKit
import PDFKit
let base = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
let pdf = NSMutableData()
var box = CGRect(x: 0, y: 0, width: 400, height: 500)
let consumer = CGDataConsumer(data: pdf)!
let context = CGContext(consumer: consumer, mediaBox: &box, nil)!
context.beginPDFPage(nil)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
("Genesis PDF validation 123" as NSString).draw(at: CGPoint(x: 30, y: 400), withAttributes: [.font: NSFont.systemFont(ofSize: 16)])
NSGraphicsContext.restoreGraphicsState()
context.endPDFPage(); context.closePDF()
try (pdf as Data).write(to: base.appendingPathComponent("fixture.pdf"))
try Data("not a pdf".utf8).write(to: base.appendingPathComponent("invalid.pdf"))
