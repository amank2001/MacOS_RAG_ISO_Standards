import SwiftUI

struct FigureViewer: View {
    let figure: Figure
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 12) {
            HStack {
                VStack(alignment: .leading) {
                    if let num = figure.figureNumber {
                        Text(num).font(.headline)
                    }
                    if let caption = figure.caption {
                        Text(caption).font(.subheadline).foregroundStyle(.secondary)
                    }
                    Text("Page \(figure.pageNumber)")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
                Spacer()
                Button("Close") { dismiss() }
            }

            if let nsImage = NSImage(contentsOfFile: figure.imagePath) {
                Image(nsImage: nsImage)
                    .resizable()
                    .scaledToFit()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ContentUnavailableView(
                    "Image unavailable",
                    systemImage: "photo.badge.exclamationmark",
                    description: Text(figure.imagePath)
                )
            }
        }
        .padding()
        .frame(minWidth: 500, minHeight: 400)
    }
}
