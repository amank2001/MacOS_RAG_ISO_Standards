import SwiftUI
import UniformTypeIdentifiers

struct QAView: View {
    @EnvironmentObject var backend: BackendClient

    @State private var question = ""
    @State private var standardFilter = ""
    @State private var response: AskResponse?
    @State private var isAsking = false
    @State private var errorMessage: String?
    @State private var pdfPreview: PDFPreviewRequest?
    @State private var isExportingPDF = false

    var body: some View {
        HSplitView {
            VStack(alignment: .leading, spacing: 16) {
                askComposer
                answerSection
            }
            .padding()
            .frame(minWidth: 380)

            sourcesPanel
                .frame(minWidth: 300)
        }
        .navigationTitle("Ask")
        .alert("Error", isPresented: .constant(errorMessage != nil)) {
            Button("OK") { errorMessage = nil }
        } message: {
            Text(errorMessage ?? "")
        }
        .sheet(item: $pdfPreview) { request in
            PDFViewerSheet(
                path: request.path,
                initialPage: request.page,
                title: request.title,
                bbox: request.bbox
            )
        }
    }

    private var askComposer: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Ask a Question")
                    .font(.title2.bold())
                Text("Answers are grounded in your indexed ISO standards and cite their sources.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 8) {
                Text("Standard")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                TextField("Filter by standard (optional), e.g. ISO 9001", text: $standardFilter)
                    .textFieldStyle(.roundedBorder)
            }

            ZStack(alignment: .topLeading) {
                TextEditor(text: $question)
                    .font(.body)
                    .scrollContentBackground(.hidden)
                    .padding(6)
                    .frame(minHeight: 96)
                if question.isEmpty {
                    Text("Type your question here…")
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, 11)
                        .padding(.vertical, 14)
                        .allowsHitTesting(false)
                }
            }
            .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 8))
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(.quaternary, lineWidth: 1)
            )

            HStack(spacing: 12) {
                Button {
                    performAsk()
                } label: {
                    Label("Ask", systemImage: "paperplane.fill")
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(question.trimmingCharacters(in: .whitespaces).isEmpty || isAsking)

                if isAsking {
                    ProgressView().controlSize(.small)
                }

                Spacer()

                if !backend.ollamaAvailable {
                    Label("Ollama offline — excerpts only", systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }
        }
    }

    @ViewBuilder
    private var answerSection: some View {
        if let response {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Label("Answer", systemImage: "text.book.closed")
                        .font(.headline)
                    Spacer()
                    if response.status == "partial" {
                        Label("Partial", systemImage: "exclamationmark.triangle")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                    if response.status != "not_found" {
                        Button {
                            exportPDF()
                        } label: {
                            Label("Export PDF", systemImage: "arrow.down.doc")
                        }
                        .disabled(isExportingPDF)
                    }
                }

                if response.status == "not_found" {
                    ContentUnavailableView(
                        "Not Found in Library",
                        systemImage: "magnifyingglass",
                        description: Text("No relevant content was found for this question in your indexed standards.")
                    )
                    .frame(maxHeight: .infinity)
                } else {
                    if !response.warnings.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(response.warnings, id: \.self) { warning in
                                Label(warning, systemImage: "exclamationmark.triangle.fill")
                                    .font(.caption)
                                    .foregroundStyle(.orange)
                            }
                        }
                        .padding(8)
                        .background(.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 6))
                    }

                    ScrollView {
                        Text(response.answer)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(12)
                    }
                    .background(.quaternary.opacity(0.25), in: RoundedRectangle(cornerRadius: 10))
                }
            }
            .frame(maxHeight: .infinity, alignment: .top)
        } else {
            ContentUnavailableView(
                "Grounded Q&A",
                systemImage: "text.book.closed",
                description: Text("Ask questions about your indexed ISO standards. Answers cite source clauses only.")
            )
            .frame(maxHeight: .infinity)
        }
    }

    @ViewBuilder
    private var sourcesPanel: some View {
        if let response {
            List {
                Section("Evidence") {
                    ForEach(response.evidence) { item in
                        EvidenceCardView(evidence: item, pdfPreview: $pdfPreview)
                    }
                }
                if !response.figures.isEmpty {
                    Section("Related Diagrams") {
                        ForEach(response.figures) { figure in
                            FigureThumbnail(figure: figure)
                        }
                    }
                }
            }
        } else {
            ContentUnavailableView(
                "Sources",
                systemImage: "doc.on.doc",
                description: Text("Cited sources will appear here.")
            )
        }
    }

    private func performAsk() {
        let q = question.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return }
        isAsking = true
        Task {
            defer { isAsking = false }
            do {
                let filter = standardFilter.isEmpty ? nil : standardFilter
                response = try await backend.ask(question: q, standardId: filter)
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func exportPDF() {
        guard let response else { return }
        isExportingPDF = true

        Task {
            defer { isExportingPDF = false }

            guard let tempURL = PDFExporter().exportPDF(question: question, response: response) else {
                errorMessage = "Failed to generate PDF."
                return
            }

            await MainActor.run {
                let savePanel = NSSavePanel()
                savePanel.title = "Save PDF Export"
                savePanel.nameFieldStringValue = tempURL.lastPathComponent
                savePanel.allowedContentTypes = [.pdf]
                savePanel.canCreateDirectories = true

                let result = savePanel.runModal()
                guard result == .OK, let destinationURL = savePanel.url else {
                    // User cancelled — clean up temp file
                    try? FileManager.default.removeItem(at: tempURL)
                    return
                }

                do {
                    // Remove existing file at destination if present
                    if FileManager.default.fileExists(atPath: destinationURL.path) {
                        try FileManager.default.removeItem(at: destinationURL)
                    }
                    try FileManager.default.copyItem(at: tempURL, to: destinationURL)
                    try FileManager.default.removeItem(at: tempURL)
                } catch {
                    errorMessage = "Failed to save PDF: \(error.localizedDescription)"
                }
            }
        }
    }
}

struct PDFPreviewRequest: Identifiable {
    let id = UUID()
    let path: String
    let page: Int?
    let title: String?
    let bbox: [Double]?
}

struct SourceCardView: View {
    let source: SearchResult
    @Binding var pdfPreview: PDFPreviewRequest?

    private var isPDF: Bool {
        source.filePath.lowercased().hasSuffix(".pdf")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !source.citation.isEmpty {
                Text(source.citation)
                    .font(.caption.bold())
                    .foregroundStyle(.tint)
            }
            Text(source.content)
                .font(.caption)
                .lineLimit(3)
                .foregroundStyle(.secondary)

            HStack(spacing: 12) {
                Button {
                    handleOpen()
                } label: {
                    Label(isPDF ? "Jump to page" : "Open document",
                          systemImage: "arrow.up.forward.square")
                        .font(.caption2)
                }
                .buttonStyle(.link)

                Button {
                    DocumentOpener.revealInFinder(source.filePath)
                } label: {
                    Label("Reveal in Finder", systemImage: "folder")
                        .font(.caption2)
                }
                .buttonStyle(.link)
            }
        }
        .padding(.vertical, 4)
    }

    private func handleOpen() {
        // Verify existence up front so we present a clear error rather than
        // letting Preview surface a confusing "no such file" dialog.
        guard DocumentOpener.exists(source.filePath) else {
            _ = DocumentOpener.open(at: source.filePath, page: source.pageNumber)
            return
        }

        if isPDF {
            pdfPreview = PDFPreviewRequest(
                path: source.filePath,
                page: source.pageNumber,
                title: source.documentTitle ?? source.fileName,
                bbox: nil
            )
        } else {
            DocumentOpener.open(at: source.filePath, page: source.pageNumber)
        }
    }
}

struct EvidenceCardView: View {
    let evidence: EvidenceItem
    @Binding var pdfPreview: PDFPreviewRequest?

    private var isPDF: Bool {
        evidence.filePath.lowercased().hasSuffix(".pdf")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !evidence.citation.isEmpty {
                Text(evidence.citation)
                    .font(.caption.bold())
                    .foregroundStyle(.tint)
            }
            Text(evidence.quotedText)
                .font(.caption)
                .lineLimit(4)
                .foregroundStyle(.secondary)
                .italic()

            if evidence.bbox != nil {
                Label("Bounding box available", systemImage: "rectangle.dashed")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }

            HStack(spacing: 12) {
                Button {
                    handleOpen()
                } label: {
                    Label(isPDF ? "Jump to page" : "Open document",
                          systemImage: "arrow.up.forward.square")
                        .font(.caption2)
                }
                .buttonStyle(.link)

                Button {
                    DocumentOpener.revealInFinder(evidence.filePath)
                } label: {
                    Label("Reveal in Finder", systemImage: "folder")
                        .font(.caption2)
                }
                .buttonStyle(.link)
            }
        }
        .padding(.vertical, 4)
    }

    private func handleOpen() {
        guard DocumentOpener.exists(evidence.filePath) else {
            _ = DocumentOpener.open(at: evidence.filePath, page: evidence.pageNumber)
            return
        }

        if isPDF {
            pdfPreview = PDFPreviewRequest(
                path: evidence.filePath,
                page: evidence.pageNumber,
                title: evidence.filePath,
                bbox: evidence.bbox
            )
        } else {
            DocumentOpener.open(at: evidence.filePath, page: evidence.pageNumber)
        }
    }
}
