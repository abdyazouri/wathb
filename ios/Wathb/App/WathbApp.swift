import SwiftUI

@main
struct WathbApp: App {
    init() { Theme.applyAppearance() }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(\.layoutDirection, .rightToLeft)
                .environment(\.locale, Locale(identifier: "ar"))
                .font(.wathb(16))
                .tint(Brand.primary)
        }
    }
}

struct RootView: View {
    @State private var session = Session.shared

    var body: some View {
        Group {
            switch session.screen {
            case .login: AuthFlow()
            case .unlock: UnlockView()
            case .home(let role):
                switch role {
                case "WORKER": WorkerTabView()
                case "BUSINESS": BusinessTabView()
                case "ADMIN": AdminTabView()
                default: OtherRoleView(role: role)
                }
            }
        }
        .animation(.default, value: session.screen)
        .task { await session.loadConfig() }
    }
}
