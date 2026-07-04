import AppKit
import Foundation

enum DocumentOpener {
    static func open(at path: String, page: Int? = nil) {
        let url = URL(fileURLWithPath: path)
        if let page, path.lowercased().hasSuffix(".pdf") {
            // Open PDF at page via Preview AppleScript
            let script = """
            tell application "Preview"
                activate
                open POSIX file "\(path)"
                delay 0.5
            end tell
            """
            if let appleScript = NSAppleScript(source: script) {
                var error: NSDictionary?
                appleScript.executeAndReturnError(&error)
            }
            NSWorkspace.shared.open(url)
        } else {
            NSWorkspace.shared.open(url)
        }
    }
}
