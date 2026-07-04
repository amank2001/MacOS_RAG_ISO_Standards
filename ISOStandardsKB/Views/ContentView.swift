import SwiftUI

struct ContentView: View {
    @EnvironmentObject var backend: BackendClient
    @State private var selection: SidebarItem? = .library

    enum SidebarItem: Hashable {
        case library
        case search
        case ask
    }

    var body: some View {
        NavigationSplitView {
            List(selection: $selection) {
                Label("Library", systemImage: "books.vertical")
                    .tag(SidebarItem.library)
                Label("Search", systemImage: "magnifyingglass")
                    .tag(SidebarItem.search)
                Label("Ask", systemImage: "bubble.left.and.text.bubble.right")
                    .tag(SidebarItem.ask)
            }
            .listStyle(.sidebar)
            .navigationSplitViewColumnWidth(min: 180, ideal: 200)
            .safeAreaInset(edge: .bottom) {
                statusBar
            }
        } detail: {
            Group {
                switch selection {
                case .library:
                    LibraryView()
                case .search:
                    SearchView()
                case .ask:
                    QAView()
                case .none:
                    Text("Select a section")
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var statusBar: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(backend.isConnected ? Color.green : Color.orange)
                .frame(width: 8, height: 8)
            Text(backend.isConnected ? "Backend connected" : "Backend offline")
                .font(.caption)
            if backend.ollamaAvailable {
                Text("• Ollama")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(.bar)
    }
}
