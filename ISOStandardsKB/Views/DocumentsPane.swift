import SwiftUI

struct DocumentsPane: View {
    @Binding var documents: [ISODocument]
    @Binding var selection: ISODocument?
    let isOnline: Bool
    let folderSelected: Bool
    let onDelete: (ISODocument) -> Void

    var body: some View {
        if folderSelected {
            List(documents, selection: $selection) { doc in
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
        } else {
            ContentUnavailableView(
                "No Folder Selected",
                systemImage: "folder",
                description: Text("Select a folder to see its documents.")
            )
        }
    }
}
