import SwiftUI

struct DeleteConfirmationSheet: View {
    let targetName: String
    let targetPath: String
    let onConfirm: (_ alsoMoveToTrash: Bool) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var alsoMoveToTrash: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Delete \(targetName)?")
                .font(.headline)
            Text(targetPath)
                .font(.caption)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
            Toggle("Also move files to Trash", isOn: $alsoMoveToTrash)
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }
                Button("Delete", role: .destructive) {
                    onConfirm(alsoMoveToTrash)
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(minWidth: 420)
    }
}
