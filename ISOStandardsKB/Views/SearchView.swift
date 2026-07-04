import SwiftUI

struct SearchView: View {
    @EnvironmentObject var backend: BackendClient

    @State private var query = ""
    @State private var mode: SearchMode = .hybrid
    @State private var standardFilter = ""
    @State private var results: [SearchResult] = []
    @State private var isSearching = false
    @State private var errorMessage: String?

    var body: some View {
        VStack(spacing: 0) {
            searchBar
            Divider()
            if isSearching {
                ProgressView("Searching...")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if results.isEmpty && !query.isEmpty {
                ContentUnavailableView.search(text: query)
            } else if results.isEmpty {
                ContentUnavailableView(
                    "Search ISO Standards",
                    systemImage: "magnifyingglass",
                    description: Text("Enter a clause number, keyword, or phrase.")
                )
            } else {
                resultsList
            }
        }
        .navigationTitle("Search")
        .alert("Search Error", isPresented: .constant(errorMessage != nil)) {
            Button("OK") { errorMessage = nil }
        } message: {
            Text(errorMessage ?? "")
        }
    }

    private var searchBar: some View {
        HStack(spacing: 12) {
            TextField("Search clauses, keywords...", text: $query)
                .textFieldStyle(.roundedBorder)
                .onSubmit { performSearch() }

            Picker("Mode", selection: $mode) {
                ForEach(SearchMode.allCases) { m in
                    Text(m.label).tag(m)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 240)

            TextField("Standard filter", text: $standardFilter)
                .textFieldStyle(.roundedBorder)
                .frame(width: 180)

            Button("Search", action: performSearch)
                .keyboardShortcut(.return, modifiers: [])
                .disabled(query.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .padding()
    }

    private var resultsList: some View {
        List(results) { result in
            SearchResultRow(result: result)
        }
    }

    private func performSearch() {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return }
        isSearching = true
        Task {
            defer { isSearching = false }
            do {
                if backend.isConnected {
                    let filter = standardFilter.isEmpty ? nil : standardFilter
                    results = try await backend.search(
                        query: q,
                        standardId: filter,
                        mode: mode
                    )
                } else {
                    results = DatabaseService.shared.keywordSearch(q)
                }
            } catch {
                results = DatabaseService.shared.keywordSearch(q)
                errorMessage = error.localizedDescription
            }
        }
    }
}

struct SearchResultRow: View {
    let result: SearchResult

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(result.citation)
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
                Spacer()
                Text(result.fileName)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Text(result.content)
                .font(.body)
                .lineLimit(4)
            Button("Open Document") {
                DocumentOpener.open(at: result.filePath, page: result.pageNumber)
            }
            .font(.caption)
            .buttonStyle(.link)
        }
        .padding(.vertical, 4)
    }
}
