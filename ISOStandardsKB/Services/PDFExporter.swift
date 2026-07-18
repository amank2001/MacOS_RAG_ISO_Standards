import Foundation
import CoreGraphics
import AppKit

/// Generates a PDF report from a Q&A response using Core Graphics.
/// The PDF includes the question, answer text, numbered citations,
/// a generation timestamp, and a disclaimer footer.
struct PDFExporter {

    // MARK: - Layout Constants

    private enum Layout {
        static let pageWidth: CGFloat = 612   // US Letter
        static let pageHeight: CGFloat = 792
        static let marginLeft: CGFloat = 54
        static let marginRight: CGFloat = 54
        static let marginTop: CGFloat = 54
        static let marginBottom: CGFloat = 72
        static let lineSpacing: CGFloat = 4

        static var contentWidth: CGFloat {
            pageWidth - marginLeft - marginRight
        }

        static var contentTop: CGFloat {
            pageHeight - marginTop
        }
    }

    // MARK: - Fonts

    private let headingFont = NSFont.boldSystemFont(ofSize: 13)
    private let bodyFont = NSFont.systemFont(ofSize: 11)
    private let smallFont = NSFont.systemFont(ofSize: 9)

    // MARK: - Public API

    /// Exports the question and response as a PDF and returns the file URL.
    /// Returns nil if PDF creation fails.
    func exportPDF(question: String, response: AskResponse) -> URL? {
        let tempDir = FileManager.default.temporaryDirectory
        let fileName = "ISOStandardsKB_Export_\(timestampForFilename()).pdf"
        let fileURL = tempDir.appendingPathComponent(fileName)

        var mediaBox = CGRect(x: 0, y: 0, width: Layout.pageWidth, height: Layout.pageHeight)

        guard let context = CGContext(fileURL as CFURL, mediaBox: &mediaBox, nil) else {
            return nil
        }

        var cursor = beginPage(context: context)

        // --- Question ---
        cursor = drawText("Question", at: cursor, font: headingFont, color: .darkGray, context: context)
        cursor -= 4
        cursor = drawWrappedText(question, at: cursor, font: bodyFont, color: .black, context: context)
        cursor -= 16

        // --- Answer ---
        cursor = drawText("Answer", at: cursor, font: headingFont, color: .darkGray, context: context)
        cursor -= 4
        cursor = drawWrappedText(response.answer, at: cursor, font: bodyFont, color: .black, context: context)
        cursor -= 16

        // --- Citations ---
        if !response.evidence.isEmpty {
            cursor = drawText("Citations", at: cursor, font: headingFont, color: .darkGray, context: context)
            cursor -= 4

            for (index, item) in response.evidence.enumerated() {
                let citationLine = "\(index + 1). \(item.citation)"
                cursor = checkPageBreak(cursor: cursor, needed: 16, context: context)
                cursor = drawWrappedText(citationLine, at: cursor, font: bodyFont, color: .black, context: context)
                cursor -= 2
            }
            cursor -= 12
        }

        // --- Timestamp ---
        let timestamp = "Generated: \(formattedTimestamp())"
        cursor = checkPageBreak(cursor: cursor, needed: 20, context: context)
        _ = drawText(timestamp, at: cursor, font: smallFont, color: .gray, context: context)

        context.endPage()
        context.closePDF()

        return fileURL
    }

    // MARK: - Page Management

    private func beginPage(context: CGContext) -> CGFloat {
        var box = CGRect(x: 0, y: 0, width: Layout.pageWidth, height: Layout.pageHeight)
        context.beginPage(mediaBox: &box)
        drawDisclaimer(context: context)
        return Layout.contentTop
    }

    /// If the cursor is too low to fit `needed` points, end the page and start a new one.
    @discardableResult
    private func checkPageBreak(cursor: CGFloat, needed: CGFloat, context: CGContext) -> CGFloat {
        if cursor - needed < Layout.marginBottom {
            context.endPage()
            return beginPage(context: context)
        }
        return cursor
    }

    // MARK: - Text Drawing

    /// Draws a single line of text. Returns the updated cursor position.
    private func drawText(
        _ text: String,
        at y: CGFloat,
        font: NSFont,
        color: NSColor,
        context: CGContext
    ) -> CGFloat {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: font,
            .foregroundColor: color
        ]
        let attrString = NSAttributedString(string: text, attributes: attributes)
        let line = CTLineCreateWithAttributedString(attrString)
        let lineHeight = font.ascender - font.descender + font.leading + Layout.lineSpacing

        let currentY = checkPageBreak(cursor: y, needed: lineHeight, context: context)

        context.saveGState()
        context.textPosition = CGPoint(x: Layout.marginLeft, y: currentY - font.ascender)
        CTLineDraw(line, context)
        context.restoreGState()

        return currentY - lineHeight
    }

    /// Draws multi-line wrapped text within the content width. Returns the updated cursor position.
    private func drawWrappedText(
        _ text: String,
        at y: CGFloat,
        font: NSFont,
        color: NSColor,
        context: CGContext
    ) -> CGFloat {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: font,
            .foregroundColor: color
        ]
        let attrString = NSAttributedString(string: text, attributes: attributes)
        let framesetter = CTFramesetterCreateWithAttributedString(attrString)

        let lineHeight = font.ascender - font.descender + font.leading + Layout.lineSpacing
        var cursor = y

        // Use CTFramesetter to get suggested line breaks
        var startIndex = 0
        let totalLength = attrString.length

        while startIndex < totalLength {
            cursor = checkPageBreak(cursor: cursor, needed: lineHeight, context: context)

            let remainingRange = CFRange(location: startIndex, length: totalLength - startIndex)
            let fitSize = CGSize(width: Layout.contentWidth, height: lineHeight * 2)
            var fitRange = CFRange(location: 0, length: 0)
            CTFramesetterSuggestFrameSizeWithConstraints(framesetter, remainingRange, nil, fitSize, &fitRange)

            if fitRange.length == 0 {
                // Safety: advance at least one character to avoid infinite loop
                fitRange.length = 1
            }

            let lineRange = CFRange(location: startIndex, length: fitRange.length)
            let lineAttrStr = attrString.attributedSubstring(from: NSRange(location: lineRange.location, length: lineRange.length))
            let line = CTLineCreateWithAttributedString(lineAttrStr)

            context.saveGState()
            context.textPosition = CGPoint(x: Layout.marginLeft, y: cursor - font.ascender)
            CTLineDraw(line, context)
            context.restoreGState()

            cursor -= lineHeight
            startIndex += fitRange.length
        }

        return cursor
    }

    // MARK: - Disclaimer

    private func drawDisclaimer(context: CGContext) {
        let disclaimer = "Generated from locally indexed sources — verify against official publications"
        let attributes: [NSAttributedString.Key: Any] = [
            .font: smallFont,
            .foregroundColor: NSColor.gray
        ]
        let attrString = NSAttributedString(string: disclaimer, attributes: attributes)
        let line = CTLineCreateWithAttributedString(attrString)

        let yPos: CGFloat = Layout.marginBottom - 24

        context.saveGState()
        context.textPosition = CGPoint(x: Layout.marginLeft, y: yPos)
        CTLineDraw(line, context)
        context.restoreGState()
    }

    // MARK: - Helpers

    private func formattedTimestamp() -> String {
        let formatter = DateFormatter()
        formatter.dateStyle = .long
        formatter.timeStyle = .short
        formatter.locale = Locale.current
        return formatter.string(from: Date())
    }

    private func timestampForFilename() -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd_HHmmss"
        return formatter.string(from: Date())
    }
}
