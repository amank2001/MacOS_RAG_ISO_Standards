import SwiftUI
import UniformTypeIdentifiers

struct LibraryView: View {
    @EnvironmentObject var backend: BackendClient
    @EnvironmentObject var indexCoordinator: IndexCoordinator

    @State private var libraries: [Library] = []
    @State private var selectedLibrary: Library?

    @State private var documents: [ISODocument] = []
    @State private var selectedDocument: ISODocument?

    @State private var clauses: [Clause] = []
    @State private var figures: [Figure] = []

    @State private var pendingLibraryDeletion: Library?
    @State private var pendingDocumentDeletion: ISODocument?

    @State private var errorMessage: String?

    var body: some View {
        HSplitView {
            FoldersPane(
                libraries: $libraries,
                selection: $selectedLibrary,
                isOnline: backend.isConnected,
                onDelete: { pendingLibraryDeletion = $0 },
                onRescan: { library in
                    Task { await rescan(library) }
                }
            )
            .frame(minWidth: 220)

            DocumentsPane(
                documents: $documents,
                selection: $selectedDocument,
                isOnline: backend.isConnected,
                folderSelected: selectedLibrary != nil,
                onDelete: { pendingDocumentDeletion = $0 }
            )
            .frame(minWidth: 260)

            DetailPane(
                document: selectedDocument,
                clauses: clauses,
                figures: figures
            )
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
                    .disabled(!backend.isConnected)
            }
        }
        .overlay(alignment: .top) {
            if !backend.isConnected {
                OfflineBanner()
            }
        }
        .sheet(item: $pendingLibraryDeletion) { library in
            DeleteConfirmationSheet(
                targetName: library.name,
                targetPath: library.path,
                onConfirm: { alsoTrash in
                    Task { await confirmDeleteLibrary(library, alsoTrash: alsoTrash) }
                }
            )
        }
        .sheet(item: $pendingDocumentDeletion) { doc in
            DeleteConfirmationSheet(
                targetName: doc.displayTitle,
                targetPath: doc.filePath,
                onConfirm: { alsoTrash in
                    Task { await confirmDeleteDocument(doc, alsoTrash: alsoTrash) }
                }
            )
        }
        .onReceive(NotificationCenter.default.publisher(for: .importFolder)) { _ in
            pickFolder()
        }
        .task {
            await loadLibraries()
        }
        .onChange(of: backend.isConnected) { oldValue, newValue in
            if !oldValue && newValue {
                Task { await loadLibraries() }
            }
        }
        .onChange(of: selectedLibrary) { _, newValue in
            selectedDocument = nil
            documents = []
            clauses = []
            figures = []
            guard let library = newValue else { return }
            Task { await loadDocuments(for: library) }
        }
        .onChange(of: selectedDocument) { _, newValue in
            clauses = []
            figures = []
            guard let doc = newValue else { return }
            Task { await loadDetails(for: doc) }
        }
        .alert("Error", isPresented: .constant(errorMessage != nil)) {
            Button("OK") { errorMessage = nil }
        } message: {
            Text(errorMessage ?? "")
        }
    }

    // MARK: - Loading

    private func loadLibraries() async {
        if backend.isConnected {
            do {
                let items = try await backend.listLibraries()
                libraries = items
            } catch {
                errorMessage = error.localizedDescription
            }
        } else {
            libraries = DatabaseService.shared.fetchLibraries()
        }
    }

    private func loadDocuments(for library: Library) async {
        if backend.isConnected {
            do {
                let items = try await backend.listDocuments(libraryId: library.id)
                // Only apply the result if the user hasn't changed selection in the meantime.
                if selectedLibrary?.id == library.id {
                    documents = items
                }
            } catch {
                errorMessage = error.localizedDescription
            }
        } else {
            let items = DatabaseService.shared.fetchDocuments(libraryId: library.id)
            if selectedLibrary?.id == library.id {
                documents = items
            }
        }
    }

    private func loadDetails(for doc: ISODocument) async {
        if backend.isConnected {
            do {
                async let loadedClauses = backend.listClauses(documentId: doc.id)
                async let loadedFigures = backend.listFigures(documentId: doc.id)
                let c = try await loadedClauses
                let f = try await loadedFigures
                if selectedDocument?.id == doc.id {
                    clauses = c
                    figures = f
                }
            } catch {
                errorMessage = error.localizedDescription
            }
        } else {
            let c = DatabaseService.shared.fetchClauses(documentId: doc.id)
            let f = DatabaseService.shared.fetchFigures(documentId: doc.id)
            if selectedDocument?.id == doc.id {
                clauses = c
                figures = f
            }
        }
    }

    // MARK: - Delete flows

    private func confirmDeleteLibrary(_ library: Library, alsoTrash: Bool) async {
        let result = await indexCoordinator.deleteFolder(library, alsoTrash: alsoTrash)
        switch result {
        case .success:
            libraries.removeAll { $0.id == library.id }
            if selectedLibrary?.id == library.id {
                selectedLibrary = nil
            }
        case .failure(let error):
            errorMessage = error.localizedDescription
        }
    }

    private func confirmDeleteDocument(_ doc: ISODocument, alsoTrash: Bool) async {
        let result = await indexCoordinator.deleteDocument(doc, alsoTrash: alsoTrash)
        switch result {
        case .success:
            documents.removeAll { $0.id == doc.id }
            if selectedDocument?.id == doc.id {
                selectedDocument = nil
            }
        case .failure(let error):
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Rescan

    private func rescan(_ library: Library) async {
        let result = await indexCoordinator.rescanFolder(library)
        switch result {
        case .success:
            do {
                let items = try await backend.listDocuments(libraryId: library.id)
                if selectedLibrary?.id == library.id {
                    documents = items
                }
            } catch {
                errorMessage = error.localizedDescription
            }
        case .failure(let error):
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Import

    private func pickFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = "Select a folder containing ISO standard documents"
        if panel.runModal() == .OK, let url = panel.url {
            Task {
                await indexCoordinator.importFolder(url, watch: true)
                await loadLibraries()
                if let library = libraries.first(where: { $0.path == url.path }) {
                    selectedLibrary = library
                }
            }
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
