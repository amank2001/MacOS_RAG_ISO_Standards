import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var backend: BackendClient

    var body: some View {
        Form {
            Section("Backend") {
                LabeledContent("API URL", value: AppConfig.apiBaseURL.absoluteString)
                LabeledContent("Status", value: backend.isConnected ? "Connected" : "Offline")
                LabeledContent("Ollama", value: backend.ollamaAvailable ? "Available" : "Not running")
                Button("Refresh Status") {
                    Task { await backend.checkHealth() }
                }
            }

            Section("Storage") {
                LabeledContent("Database", value: AppConfig.dbPath.path)
                LabeledContent("Figures", value: AppConfig.figuresPath.path)
            }

            Section("Getting Started") {
                Text("1. Run: python3 isokb.py serve")
                Text("2. Install Ollama and pull models: ollama pull nomic-embed-text && ollama pull llama3.1:8b")
                Text("3. Import your ISO standards folder via Library → Import Folder")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .formStyle(.grouped)
        .frame(width: 480, height: 320)
    }
}
