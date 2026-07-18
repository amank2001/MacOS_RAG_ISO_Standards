import SwiftUI

struct DocumentDetailView: View {
    let document: ISODocument
    let clauses: [Clause]
    let figures: [Figure]

    @State private var selectedClause: Clause?
    @State private var pdfPreview: PDFPreviewRequest?

    var body: some View {
        HSplitView {
            VStack(alignment: .leading, spacing: 0) {
                Text("Clauses")
                    .font(.headline)
                    .padding(.horizontal, 12)
                    .padding(.top, 12)
                    .padding(.bottom, 6)
                if clauses.isEmpty {
                    ContentUnavailableView(
                        "No Clauses",
                        systemImage: "list.bullet.indent",
                        description: Text("No clauses detected for this document.")
                    )
                } else {
                    List(clauses, selection: $selectedClause) { clause in
                        Text(clause.displayName)
                            .padding(.leading, CGFloat(max(0, clause.level - 1)) * 12)
                            .tag(clause)
                    }
                    .listStyle(.inset)
                }
            }
            .frame(minWidth: 240, idealWidth: 300)

            VStack(alignment: .leading, spacing: 16) {
                header
                Divider()
                Text("Figures")
                    .font(.headline)
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
            .frame(minWidth: 360)
        }
        .sheet(item: $pdfPreview) { request in
            PDFViewerSheet(
                path: request.path,
                initialPage: request.page,
                title: request.title,
                bbox: request.bbox
            )
        }
    }

    private var isPDF: Bool {
        document.filePath.lowercased().hasSuffix(".pdf")
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
                Button("Reveal in Finder") {
                    DocumentOpener.revealInFinder(document.filePath)
                }
                Button("Open Original") {
                    handleOpen()
                }
            }
            .font(.caption)
        }
    }

    private func handleOpen() {
        guard DocumentOpener.exists(document.filePath) else {
            _ = DocumentOpener.open(at: document.filePath)
            return
        }
        if isPDF {
            pdfPreview = PDFPreviewRequest(
                path: document.filePath,
                page: nil,
                title: document.displayTitle,
                bbox: nil
            )
        } else {
            DocumentOpener.open(at: document.filePath)
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
