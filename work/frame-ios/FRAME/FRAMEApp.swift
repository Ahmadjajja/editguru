import SwiftUI

@main
struct FRAMEApp: App {
    @State private var store = ProjectStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(store)
                .preferredColorScheme(.dark)
        }
    }
}
