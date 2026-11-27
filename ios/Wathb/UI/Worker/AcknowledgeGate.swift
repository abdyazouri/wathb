import SwiftUI

/// How the worker proves it is them before «استلمت»: Face ID / Touch ID / the phone passcode,
/// or, on a phone with none of those, the account password (checked by the server, 403 if wrong).
/// Disputing needs neither. Port of android WageAcknowledgeGate.kt.
@MainActor
@Observable
final class AcknowledgeGate {
    var passwordFor: String?
    var password = ""
    var error: String?
    fileprivate var onAcknowledge: ((String, String?) -> Void)?

    func request(_ wageId: String) {
        if Biometrics.isAvailable {
            Task {
                if let message = await Biometrics.authenticate(reason: "تأكيد استلام الأجر") {
                    error = message
                } else {
                    onAcknowledge?(wageId, nil)
                }
            }
        } else {
            password = ""
            passwordFor = wageId
        }
    }
}

private struct AcknowledgeGateModifier: ViewModifier {
    @Bindable var gate: AcknowledgeGate
    let onAcknowledge: (String, String?) -> Void

    func body(content: Content) -> some View {
        content
            .onAppear { gate.onAcknowledge = onAcknowledge }
            .alert("تأكيد استلام الأجر", isPresented: Binding(
                get: { gate.passwordFor != nil }, set: { if !$0 { gate.passwordFor = nil } })
            ) {
                SecureField("كلمة المرور", text: $gate.password)
                Button("تأكيد") {
                    if let id = gate.passwordFor, !gate.password.isEmpty { onAcknowledge(id, gate.password) }
                    gate.password = ""
                    gate.passwordFor = nil
                }
                Button("إلغاء", role: .cancel) { gate.password = "" }
            } message: {
                Text("لا يوجد Face ID ولا رمز قفل على هذا الهاتف. أدخل كلمة مرور حسابك لتأكيد أنك استلمت الأجر.")
            }
            .toast($gate.error)
    }
}

extension View {
    func acknowledgeGate(_ gate: AcknowledgeGate, onAcknowledge: @escaping (String, String?) -> Void) -> some View {
        modifier(AcknowledgeGateModifier(gate: gate, onAcknowledge: onAcknowledge))
    }
}
