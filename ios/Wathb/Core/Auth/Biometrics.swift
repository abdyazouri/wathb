import Foundation
import LocalAuthentication

/// Face ID / Touch ID, falling back to the phone passcode (like android BIOMETRIC_WEAK | DEVICE_CREDENTIAL).
enum Biometrics {
    /// The phone has Face ID, Touch ID or at least a passcode.
    static var isAvailable: Bool {
        LAContext().canEvaluatePolicy(.deviceOwnerAuthentication, error: nil)
    }

    /// «بصمتك» on Touch ID phones, «وجهك» on Face ID phones.
    static var name: String {
        let ctx = LAContext()
        _ = ctx.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil)
        switch ctx.biometryType {
        case .faceID: return "وجهك"
        case .touchID: return "بصمتك"
        default: return "رمز القفل"
        }
    }

    static var systemImage: String {
        let ctx = LAContext()
        _ = ctx.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil)
        return ctx.biometryType == .touchID ? "touchid" : "faceid"
    }

    /// Nil on success; otherwise an Arabic message (nil also never means "skipped").
    static func authenticate(reason: String) async -> String? {
        let ctx = LAContext()
        ctx.localizedCancelTitle = "إلغاء"
        do {
            return try await ctx.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason) ? nil : "لم يتم التحقق."
        } catch let e as LAError {
            switch e.code {
            case .userCancel, .systemCancel, .appCancel: return "تم الإلغاء."
            case .biometryLockout: return "تم قفل التحقق مؤقتًا. افتح قفل الهاتف ثم حاول مجددًا."
            case .passcodeNotSet: return "لا يوجد رمز قفل على الهاتف."
            default: return "لم يتم التحقق. حاول مرة أخرى."
            }
        } catch {
            return "لم يتم التحقق. حاول مرة أخرى."
        }
    }
}
