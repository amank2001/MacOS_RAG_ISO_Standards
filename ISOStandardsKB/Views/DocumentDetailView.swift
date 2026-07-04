import SwiftUI

struct DocumentDetailView: View {
    let document: ISODocument
    let clauses: [Clause]
    let figures: [Figure]

    @State private var selectedClause: Clause?

    var body: some View {
        HSplitView {
            List(clauses, selection: $selectedClause) { clause in
                Text(clause.displayName)
                    .padding(.leading, CGFloat(max(0, clause.level - 1)) * 12)
                    .tag(clause)
            }
            .frame(minWidth: 220)

            VStack(alignment: .leading, spacing: 12) {
                header
                if figures.isEmpty {
                    ContentUnavailableView(
                        "No Figures",
                        systemImage: "photo",
                        description: Text("No diagrams extracted for this document.")
                    )
                } else {
                    FigureGridView(figures: figures)
                }
                Spacer()
            }
            .padding()
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(document.displayTitle)
                .font(.title2.bold())
            HStack {
                if let sid = document.standardId {
                    Text(sid).foregroundStyle(.secondary)
                }
                Text("• \(document.pageCount) pages")
                    .foregroundStyle(.secondary)
                Spacer()
                Button("Open Original") {
                    DocumentOpener.open(at: document.filePath)
                }
            }
            .font(.caption)
        }
    }
}

struct FigureGridView: View {
    let figures: [Figure]
    @State private var selectedFigure: Figure?

    var body: some View {
        ScrollView {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 160))], spacing: 12) {
                ForEach(figures) { figure in
                    FigureThumbnail(figure: figure)
                        .onTapGesture { selectedFigure = figure }
                }
            }
        }
        .sheet(item: $selectedFigure) { figure in
            FigureViewer(figure: figure)
        }
    }
}

struct FigureThumbnail: View {
    let figure: Figure

    var body: some View {
        VStack(spacing: 4) {
            if let nsImage = NSImage(contentsOfFile: figure.imagePath) {
                Image(nsImage: nsImage)
                    .resizable()
                    .scaledToFit()
                    .frame(height: 120)
            } else {
                Image(systemName: "photo")
                    .frame(height: 120)
            }
            if let num = figure.figureNumber {
                Text(num).font(.caption)
            }
            Text("p.\(figure.pageNumber)").font(.caption2).foregroundStyle(.secondary)
        }
        .padding(8)
        .background(.quaternary.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}
