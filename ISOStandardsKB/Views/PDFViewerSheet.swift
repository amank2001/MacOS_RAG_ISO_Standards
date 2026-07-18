import AppKit
import PDFKit
import SwiftUI

/// Sheet that renders a PDF from disk with PDFKit and jumps to `initialPage`.
/// When `bbox` data is available (4 elements: [x0, y0, x1, y1]), a semi-transparent
/// yellow highlight annotation is added at those coordinates on the target page.
/// Falls back to a clear error state if the file is missing.
struct PDFViewerSheet: View {
    let path: String
    let initialPage: Int?
    let title: String?
    let bbox: [Double]?

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            header
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(.bar)
            Divider()

            if let url = fileURL {
                PDFKitRepresentable(url: url, initialPage: initialPage, bbox: bbox)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ContentUnavailableView(
                    "File not found",
                    systemImage: "doc.questionmark",
                    description: Text(path)
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .frame(minWidth: 720, minHeight: 540)
    }

    private var fileURL: URL? {
        let expanded = (path as NSString).expandingTildeInPath
        guard FileManager.default.fileExists(atPath: expanded) else { return nil }
        return URL(fileURLWithPath: expanded)
    }

    private var header: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title ?? (path as NSString).lastPathComponent)
                    .font(.headline)
                    .lineLimit(1)
                if let initialPage {
                    Text("Page \(initialPage)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            Button {
                DocumentOpener.revealInFinder(path)
            } label: {
                Label("Reveal in Finder", systemImage: "folder")
            }
            .buttonStyle(.borderless)

            Button {
                DocumentOpener.open(at: path)
            } label: {
                Label("Open in Preview", systemImage: "arrow.up.forward.app")
            }
            .buttonStyle(.borderless)

            Button("Done") { dismiss() }
                .keyboardShortcut(.cancelAction)
        }
    }
}

private struct PDFKitRepresentable: NSViewRepresentable {
    let url: URL
    let initialPage: Int?
    let bbox: [Double]?

    func makeNSView(context: Context) -> PDFView {
        let view = PDFView()
        view.autoScales = true
        view.displayMode = .singlePageContinuous
        view.displayDirection = .vertical
        view.backgroundColor = .textBackgroundColor
        loadDocument(into: view)
        return view
    }

    func updateNSView(_ nsView: PDFView, context: Context) {
        // Only reload if the URL changed to avoid resetting the user's scroll
        // position on unrelated state updates.
        if nsView.document?.documentURL != url {
            loadDocument(into: nsView)
        }
    }

    private func loadDocument(into view: PDFView) {
        guard let document = PDFDocument(url: url) else { return }
        view.document = document
        guard
            let target = initialPage,
            target > 0,
            let page = document.page(at: max(0, target - 1))
        else { return }

        // Add highlight annotation if bbox data is available with 4 valid elements.
        if let bbox = bbox, bbox.count >= 4 {
            let x0 = CGFloat(bbox[0])
            let y0 = CGFloat(bbox[1])
            let x1 = CGFloat(bbox[2])
            let y1 = CGFloat(bbox[3])
            let rect = CGRect(x: x0, y: y0, width: x1 - x0, height: y1 - y0)

            let annotation = PDFAnnotation(bounds: rect, forType: .highlight, withProperties: nil)
            annotation.color = NSColor.yellow.withAlphaComponent(0.3)
            page.addAnnotation(annotation)
        }

        // Defer to next runloop tick so PDFView has finished layout before we
        // scroll; otherwise the jump is silently ignored on first display.
        DispatchQueue.main.async {
            view.go(to: page)
        }
    }
}
