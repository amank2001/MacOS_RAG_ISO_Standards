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
        VStack(spacing: 12) {
            // Primary search row
            HStack(spacing: 10) {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField("Search clauses, keywords, or phrases…", text: $query)
                        .textFieldStyle(.plain)
                        .onSubmit { performSearch() }
                    if !query.isEmpty {
                        Button {
                            query = ""
                            results = []
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                        .help("Clear")
                    }
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
                .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))

                Button("Search", action: performSearch)
                    .keyboardShortcut(.return, modifiers: [])
                    .buttonStyle(.borderedProminent)
                    .disabled(query.trimmingCharacters(in: .whitespaces).isEmpty)
            }

            // Options row — labels aligned with their controls
            HStack(spacing: 20) {
                HStack(spacing: 8) {
                    Text("Mode")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Picker("Mode", selection: $mode) {
                        ForEach(SearchMode.allCases) { m in
                            Text(m.label).tag(m)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.segmented)
                    .fixedSize()
                }

                Divider()
                    .frame(height: 18)

                HStack(spacing: 8) {
                    Text("Standard")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    TextField("e.g. ISO 9001", text: $standardFilter)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 160)
                }

                Spacer()
            }
        }
        .padding()
        .background(.bar)
    }

    private var resultsList: some View {
        List {
            Section {
                ForEach(results) { result in
                    SearchResultRow(result: result)
                }
            } header: {
                Text("\(results.count) result\(results.count == 1 ? "" : "s")")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .listStyle(.inset)
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
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                if !result.citation.isEmpty {
                    Text(result.citation)
                        .font(.caption.bold())
                        .foregroundStyle(.tint)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(.tint.opacity(0.12), in: Capsule())
                }
                Spacer()
                Label(result.fileName, systemImage: "doc")
                    .font(.caption.bold())
                    .foregroundStyle(.tint)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(.tint.opacity(0.12), in: Capsule())
                    .lineLimit(1)
            }

            Text(result.content)
                .font(.body)
                .foregroundStyle(.primary)
                .lineLimit(4)

            Button {
                DocumentOpener.open(at: result.filePath, page: result.pageNumber)
            } label: {
                Label("Open Document", systemImage: "arrow.up.forward.square")
                    .font(.caption)
            }
            .buttonStyle(.link)
        }
        .padding(12)
        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 10))
        .listRowSeparator(.hidden)
        .listRowInsets(EdgeInsets(top: 4, leading: 8, bottom: 4, trailing: 8))
    }
}
