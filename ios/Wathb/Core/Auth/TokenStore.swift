import Foundation
import Security

/// The session, kept in the Keychain (this device only, readable after the first unlock).
/// Matches android TokenManager: tokens, role and the «الدخول بالوجه» choice, all wiped together.
enum TokenStore {
    private static let service = "com.wathb.app.session"
    private static let lock = NSLock()

    static var accessToken: String? { read("access_token") }
    static var refreshToken: String? { read("refresh_token") }
    static var isLoggedIn: Bool { accessToken != nil }

    static var role: String? {
        get { read("user_role") }
        set { write("user_role", newValue) }
    }

    /// The user chose to open the app with Face ID / passcode. Cleared with the session,
    /// so after logging out or an expired session the password is needed again.
    static var biometricLogin: Bool {
        get { read("biometric_login") == "1" }
        set { write("biometric_login", newValue ? "1" : nil) }
    }

    static func save(access: String, refresh: String) {
        write("access_token", access)
        write("refresh_token", refresh)
    }

    static func clear() {
        for key in ["access_token", "refresh_token", "user_role", "biometric_login"] { write(key, nil) }
    }

    /// Keychain items outlive the app; a fresh install must not inherit an old session.
    static func clearIfFreshInstall() {
        let flag = "wathb.installed"
        if !UserDefaults.standard.bool(forKey: flag) {
            clear()
            UserDefaults.standard.set(true, forKey: flag)
        }
    }

    // MARK: Keychain

    private static func query(_ key: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: key]
    }

    private static func read(_ key: String) -> String? {
        lock.lock(); defer { lock.unlock() }
        var q = query(key)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func write(_ key: String, _ value: String?) {
        lock.lock(); defer { lock.unlock() }
        SecItemDelete(query(key) as CFDictionary)
        guard let value else { return }
        var q = query(key)
        q[kSecValueData as String] = Data(value.utf8)
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(q as CFDictionary, nil)
    }
}
