import SwiftUI

struct OfflineBanner: View {
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
            Text("Backend is not running. Destructive actions are disabled.")
                .font(.callout)
                .fontWeight(.medium)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .foregroundStyle(.white)
        .background(
            Capsule()
                .fill(Color.red)
                .shadow(radius: 4, y: 2)
        )
        .padding(.top, 12)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Backend is not running. Destructive actions are disabled.")
    }
}

#Preview {
    OfflineBanner()
        .padding()
}
