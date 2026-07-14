import AppKit
import Foundation

/// Opens indexed documents from disk with clear diagnostics when the on-disk
/// file is missing or macOS refuses to launch it.
enum DocumentOpener {
    enum OpenError: LocalizedError {
        case fileMissing(String)
        case openFailed(String)

        var errorDescription: String? {
            switch self {
            case .fileMissing(let path):
                return "The file is no longer at:\n\(path)\n\nIt may have been moved, renamed, or the containing volume unmounted since it was indexed. Rescan the library to refresh the paths."
            case .openFailed(let path):
                return "macOS refused to open:\n\(path)"
            }
        }
    }

    /// Opens `path` in the default macOS application. Presents an alert if the
    /// file is missing or the launch fails, and returns the underlying error.
    ///
    /// - Parameters:
    ///   - path: Absolute file system path, as stored in the database.
    ///   - page: Optional 1-based page number. Ignored here; PDF page jumps
    ///           are handled by the in-app PDF viewer.
    @discardableResult
    static func open(at path: String, page: Int? = nil) -> OpenError? {
        _ = page  // Preview cannot open a PDF at a specific page; handled by PDFViewerSheet.

        let expanded = expandedPath(path)
        let url = URL(fileURLWithPath: expanded)

        guard FileManager.default.fileExists(atPath: expanded) else {
            presentMissingFileAlert(path: expanded)
            return .fileMissing(expanded)
        }

        if NSWorkspace.shared.open(url) {
            return nil
        }

        presentAlert(
            title: "Couldn't open file",
            message: "macOS was unable to open:\n\(expanded)"
        )
        return .openFailed(expanded)
    }

    /// Reveals `path` in Finder. If the file itself is gone, opens its parent
    /// directory when that still exists.
    static func revealInFinder(_ path: String) {
        let expanded = expandedPath(path)
        let fm = FileManager.default

        if fm.fileExists(atPath: expanded) {
            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: expanded)])
            return
        }

        let parent = (expanded as NSString).deletingLastPathComponent
        if !parent.isEmpty, fm.fileExists(atPath: parent) {
            NSWorkspace.shared.open(URL(fileURLWithPath: parent))
            return
        }

        presentMissingFileAlert(path: expanded)
    }

    /// Whether `path` currently exists on disk.
    static func exists(_ path: String) -> Bool {
        FileManager.default.fileExists(atPath: expandedPath(path))
    }

    // MARK: - Helpers

    private static func expandedPath(_ path: String) -> String {
        (path as NSString).expandingTildeInPath
    }

    private static func presentMissingFileAlert(path: String) {
        let alert = NSAlert()
        alert.messageText = "File not found"
        alert.informativeText = "The file is no longer at:\n\(path)\n\nIt may have been moved, renamed, or the containing volume unmounted since it was indexed. Rescan the library to refresh the paths."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "OK")
        let parent = (path as NSString).deletingLastPathComponent
        if !parent.isEmpty, FileManager.default.fileExists(atPath: parent) {
            alert.addButton(withTitle: "Open Enclosing Folder")
        }
        let response = alert.runModal()
        if response == .alertSecondButtonReturn, !parent.isEmpty {
            NSWorkspace.shared.open(URL(fileURLWithPath: parent))
        }
    }

    private static func presentAlert(title: String, message: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }
}
