import AppKit
import PDFKit
import SwiftUI

/// Sheet that renders a PDF from disk with PDFKit and jumps to `initialPage`.
/// Falls back to a clear error state if the file is missing.
struct PDFViewerSheet: View {
    let path: String
    let initialPage: Int?
    let title: String?

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            header
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(.bar)
            Divider()

            if let url = fileURL {
                PDFKitRepresentable(url: url, initialPage: initialPage)
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
        // Defer to next runloop tick so PDFView has finished layout before we
        // scroll; otherwise the jump is silently ignored on first display.
        DispatchQueue.main.async {
            view.go(to: page)
        }
    }
}
