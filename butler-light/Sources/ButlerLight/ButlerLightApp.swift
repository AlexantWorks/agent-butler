import SwiftUI

@main
struct ButlerLightApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup(L10n.t("Butler Light")) {
            ContentView()
                .environmentObject(model)
                .frame(minWidth: 900, minHeight: 600)
        }
        .defaultSize(width: 940, height: 640)
        .windowStyle(.titleBar)
    }
}
