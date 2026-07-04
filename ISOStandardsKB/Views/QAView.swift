import SwiftUI

struct QAView: View {
    @EnvironmentObject var backend: BackendClient

    @State private var question = ""
    @State private var standardFilter = ""
    @State private var response: AskResponse?
    @State private var isAsking = false
    @State private var errorMessage: String?

    var body: some View {
        HSplitView {
            VStack(alignment: .leading, spacing: 12) {
                Text("Ask a Question")
                    .font(.title2.bold())

                TextField("Filter by standard (optional)", text: $standardFilter)
                    .textFieldStyle(.roundedBorder)

                TextEditor(text: $question)
                    .font(.body)
                    .frame(minHeight: 100)
                    .overlay(
                        RoundedRectangle(cornerRadius: 6)
                            .stroke(.quaternary, lineWidth: 1)
                    )

                HStack {
                    Button("Ask") { performAsk() }
                        .keyboardShortcut(.return, modifiers: .command)
                        .disabled(question.trimmingCharacters(in: .whitespaces).isEmpty || isAsking)

                    if isAsking {
                        ProgressView().controlSize(.small)
                    }

                    if !backend.ollamaAvailable {
                        Text("Ollama offline — excerpts only")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }

                if let response {
                    ScrollView {
                        Text(response.answer)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                } else {
                    ContentUnavailableView(
                        "Grounded Q&A",
                        systemImage: "text.book.closed",
                        description: Text("Ask questions about your indexed ISO standards. Answers cite source clauses only.")
                    )
                }

                Spacer()
            }
            .padding()
            .frame(minWidth: 360)

            sourcesPanel
                .frame(minWidth: 300)
        }
        .navigationTitle("Ask")
        .alert("Error", isPresented: .constant(errorMessage != nil)) {
            Button("OK") { errorMessage = nil }
        } message: {
            Text(errorMessage ?? "")
        }
    }

    @ViewBuilder
    private var sourcesPanel: some View {
        if let response {
            List {
                Section("Sources") {
                    ForEach(response.sources) { source in
                        SourceCardView(source: source)
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
}

struct SourceCardView: View {
    let source: SearchResult

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(source.citation)
                .font(.caption.bold())
            Text(source.content)
                .font(.caption)
                .lineLimit(3)
                .foregroundStyle(.secondary)
            Button("Jump to page") {
                DocumentOpener.open(at: source.filePath, page: source.pageNumber)
            }
            .font(.caption2)
            .buttonStyle(.link)
        }
        .padding(.vertical, 2)
    }
}
