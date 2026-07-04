import SwiftUI
import UniformTypeIdentifiers

struct LibraryView: View {
    @EnvironmentObject var backend: BackendClient
    @EnvironmentObject var indexCoordinator: IndexCoordinator

    @State private var documents: [ISODocument] = []
    @State private var selectedDocument: ISODocument?
    @State private var clauses: [Clause] = []
    @State private var figures: [Figure] = []
    @State private var errorMessage: String?

    var body: some View {
        HSplitView {
            documentList
                .frame(minWidth: 260)
            if let doc = selectedDocument {
                DocumentDetailView(
                    document: doc,
                    clauses: clauses,
                    figures: figures
                )
            } else {
                ContentUnavailableView(
                    "No Document Selected",
                    systemImage: "doc.text",
                    description: Text("Import a folder of ISO standards to get started.")
                )
            }
        }
        .navigationTitle("Library")
        .toolbar {
            ToolbarItemGroup {
                if indexCoordinator.isIndexing {
                    ProgressView()
                        .controlSize(.small)
                    Text(indexCoordinator.lastMessage)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Button("Import Folder") { pickFolder() }
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .importFolder)) { _ in
            pickFolder()
        }
        .task { await reload() }
        .onChange(of: selectedDocument?.id) { _, newId in
            guard let newId else { return }
            Task { await loadDetails(documentId: newId) }
        }
        .alert("Error", isPresented: .constant(errorMessage != nil)) {
            Button("OK") { errorMessage = nil }
        } message: {
            Text(errorMessage ?? "")
        }
    }

    private var documentList: some View {
        List(documents, selection: $selectedDocument) { doc in
            VStack(alignment: .leading, spacing: 2) {
                Text(doc.displayTitle)
                    .fontWeight(.medium)
                HStack {
                    if let sid = doc.standardId {
                        Text(sid).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    StatusBadge(status: doc.status)
                }
            }
            .tag(doc)
        }
    }

    private func pickFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = "Select a folder containing ISO standard documents"
        if panel.runModal() == .OK, let url = panel.url {
            Task {
                await indexCoordinator.importFolder(url, watch: true)
                await reload()
            }
        }
    }

    private func reload() async {
        do {
            if backend.isConnected {
                documents = try await backend.listDocuments()
            } else {
                documents = DatabaseService.shared.fetchDocuments()
            }
        } catch {
            documents = DatabaseService.shared.fetchDocuments()
            errorMessage = error.localizedDescription
        }
    }

    private func loadDetails(documentId: Int) async {
        do {
            if backend.isConnected {
                clauses = try await backend.listClauses(documentId: documentId)
                figures = try await backend.listFigures(documentId: documentId)
            } else {
                clauses = DatabaseService.shared.fetchClauses(documentId: documentId)
                figures = []
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

struct StatusBadge: View {
    let status: String

    var body: some View {
        Text(status)
            .font(.caption2)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(backgroundColor.opacity(0.2))
            .foregroundStyle(backgroundColor)
            .clipShape(Capsule())
    }

    private var backgroundColor: Color {
        switch status {
        case "indexed": return .green
        case "indexing", "pending": return .orange
        case "error": return .red
        default: return .gray
        }
    }
}
