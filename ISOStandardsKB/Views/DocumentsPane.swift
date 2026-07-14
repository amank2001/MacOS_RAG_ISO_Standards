import SwiftUI

struct DocumentsPane: View {
    @Binding var documents: [ISODocument]
    @Binding var selection: ISODocument?
    let isOnline: Bool
    let isIndexing: Bool
    let onDelete: (ISODocument) -> Void
    let onRescan: () -> Void

    var body: some View {
        Group {
            if documents.isEmpty {
                ContentUnavailableView(
                    "No Documents",
                    systemImage: "doc.text.magnifyingglass",
                    description: Text(isIndexing
                        ? "Indexing in progress. Documents will appear as they are processed."
                        : "This folder has no indexed documents yet.")
                )
            } else {
                List(documents, selection: $selection) { doc in
                    row(for: doc)
                        .tag(doc)
                        .contextMenu {
                            Button(role: .destructive) {
                                onDelete(doc)
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                            .disabled(!isOnline)
                        }
                        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                            Button(role: .destructive) {
                                onDelete(doc)
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                            .disabled(!isOnline)
                        }
                }
                .listStyle(.inset)
            }
        }
        .toolbar {
            ToolbarItem {
                Button {
                    onRescan()
                } label: {
                    Label("Rescan", systemImage: "arrow.clockwise")
                }
                .disabled(!isOnline)
            }
        }
    }

    @ViewBuilder
    private func row(for doc: ISODocument) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon(for: doc.fileType))
                .font(.title3)
                .foregroundStyle(.tint)
                .frame(width: 28)

            VStack(alignment: .leading, spacing: 3) {
                Text(doc.displayTitle)
                    .fontWeight(.medium)
                    .lineLimit(1)
                HStack(spacing: 8) {
                    if let sid = doc.standardId {
                        Text(sid)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Text("\(doc.pageCount) pages")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            StatusBadge(status: doc.status)

            Image(systemName: "chevron.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
    }

    private func icon(for fileType: String) -> String {
        switch fileType.lowercased() {
        case "pdf": return "doc.richtext"
        case "docx", "doc": return "doc.text"
        default: return "doc"
        }
    }
}
