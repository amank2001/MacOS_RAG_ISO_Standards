import SwiftUI

struct DetailPane: View {
    let document: ISODocument?
    let clauses: [Clause]
    let figures: [Figure]

    var body: some View {
        if let document {
            DocumentDetailView(
                document: document,
                clauses: clauses,
                figures: figures
            )
        } else {
            ContentUnavailableView(
                "No Document Selected",
                systemImage: "doc.text",
                description: Text("Select a document to view its clauses and figures.")
            )
        }
    }
}
