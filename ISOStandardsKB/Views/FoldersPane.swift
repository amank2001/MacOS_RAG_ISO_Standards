import SwiftUI

struct FoldersPane: View {
    @Binding var libraries: [Library]
    @Binding var selection: Library?
    let isOnline: Bool
    let onDelete: (Library) -> Void
    let onRescan: (Library) -> Void

    var body: some View {
        Group {
            if libraries.isEmpty {
                ContentUnavailableView {
                    Label("No Folders Yet", systemImage: "folder.badge.plus")
                } description: {
                    Text("Import a folder of ISO standard documents to start building your knowledge base.")
                }
            } else {
                List(libraries, selection: $selection) { library in
                    row(for: library)
                        .tag(library)
                        .contextMenu {
                            Button {
                                onRescan(library)
                            } label: {
                                Label("Rescan", systemImage: "arrow.clockwise")
                            }
                            .disabled(!isOnline)

                            Button(role: .destructive) {
                                onDelete(library)
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                            .disabled(!isOnline)
                        }
                }
                .listStyle(.inset)
            }
        }
    }

    @ViewBuilder
    private func row(for library: Library) -> some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: "folder.fill")
                .font(.title3)
                .foregroundStyle(.tint)
                .frame(width: 28)

            VStack(alignment: .leading, spacing: 3) {
                Text(library.name)
                    .fontWeight(.medium)
                    .lineLimit(1)
                Text(library.path)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            Spacer()

            Button {
                onRescan(library)
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.borderless)
            .help("Rescan")
            .disabled(!isOnline)

            Button(role: .destructive) {
                onDelete(library)
            } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(.borderless)
            .help("Delete")
            .disabled(!isOnline)

            Image(systemName: "chevron.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
    }
}
