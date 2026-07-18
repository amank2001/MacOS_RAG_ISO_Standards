import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        OllamaProcessManager.shared.stopIfOwned()
    }
}

@main
struct ISOStandardsKBApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var backend = BackendClient.shared
    @StateObject private var indexCoordinator = IndexCoordinator()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(backend)
                .environmentObject(indexCoordinator)
                .task {
                    await OllamaProcessManager.shared.startIfNeeded()
                    await backend.checkHealth()
                }
        }
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Import Folder...") {
                    NotificationCenter.default.post(name: .importFolder, object: nil)
                }
                .keyboardShortcut("O", modifiers: [.command, .shift])
            }
        }

        Settings {
            SettingsView()
                .environmentObject(backend)
        }
    }
}

extension Notification.Name {
    static let importFolder = Notification.Name("importFolder")
}
