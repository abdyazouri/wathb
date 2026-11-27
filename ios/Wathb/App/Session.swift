import Foundation
import Observation

/// Which part of the app is showing: the login screens, the Face ID lock, or a role's home.
@MainActor
@Observable
final class Session {
    static let shared = Session()

    enum Screen: Equatable { case login, unlock, home(role: String) }

    var screen: Screen
    /// Shown once on the login screen (e.g. the session expired).
    var notice: String?
    /// WhatsApp support number from app/config/; empty hides the button.
    var supportWhatsapp = ""

    private init() {
        TokenStore.clearIfFreshInstall()
        if !TokenStore.isLoggedIn {
            screen = .login
        } else if TokenStore.biometricLogin {
            screen = .unlock
        } else {
            screen = .home(role: TokenStore.role ?? "")
        }
    }

    func signedIn(role: String) { screen = .home(role: role) }

    func unlocked() { screen = .home(role: TokenStore.role ?? "") }

    func logout() async {
        await API.logout()
        screen = .login
    }

    /// The account was deleted; the server already ended the session.
    func accountDeleted() {
        TokenStore.clear()
        screen = .login
    }

    /// The server refused the refresh token.
    static func expire() async {
        TokenStore.clear()
        shared.notice = "انتهت الجلسة، سجّل الدخول من جديد."
        shared.screen = .login
    }

    func loadConfig() async {
        if let config = try? await API.config() { supportWhatsapp = config.supportWhatsapp ?? "" }
    }
}
