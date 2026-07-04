import SwiftUI

@main
struct ISOStandardsKBApp: App {
    @StateObject private var backend = BackendClient.shared
    @StateObject private var indexCoordinator = IndexCoordinator()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(backend)
                .environmentObject(indexCoordinator)
                .task {
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
