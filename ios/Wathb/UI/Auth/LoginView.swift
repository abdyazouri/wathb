import SwiftUI

/// Login → «سجّل الآن» → terms → registration.
struct AuthFlow: View {
    enum Step: Hashable { case consent, register(consentVersion: Int) }
    @State private var path: [Step] = []

    var body: some View {
        NavigationStack(path: $path) {
            LoginView(onRegister: { path.append(.consent) })
                .navigationDestination(for: Step.self) { step in
                    switch step {
                    case .consent:
                        ConsentView { version in path.append(.register(consentVersion: version)) }
                    case .register(let version):
                        RegisterView(consentVersion: version, onLogin: { path.removeAll() })
                    }
                }
        }
    }
}

struct LoginView: View {
    let onRegister: () -> Void

    @State private var phone = ""
    @State private var password = ""
    @State private var loading = false
    @State private var toast: String?
    /// After a password login: offer Face ID for next time (once per login).
    @State private var offerBiometricFor: String?
    @State private var showOffer = false
    private var session: Session { .shared }

    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                // Brand hero
                VStack(spacing: 8) {
                    Text("وَثْب").font(.wathb(56, .black)).foregroundStyle(Brand.gold)
                    Text("خطوتك للشغل الجاي").font(.wathb(16)).foregroundStyle(.white.opacity(0.85))
                }
                .frame(maxWidth: .infinity, minHeight: 260)
                .background(Brand.deepTeal)

                VStack(spacing: 16) {
                    Text("تسجيل الدخول").font(.wathb(20, .bold)).foregroundStyle(Brand.primary)
                        .padding(.bottom, 8)
                    FormField(label: "رقم الهاتف", text: $phone, keyboard: .phonePad, contentType: .username)
                    PasswordField(text: $password)
                    LoadingButton(title: "دخول", loading: loading, action: login).padding(.top, 12)
                    Button("ليس لديك حساب؟ سجّل الآن", action: onRegister)
                        .font(.wathb(15)).foregroundStyle(Brand.teal)
                }
                .padding(.horizontal, 24).padding(.vertical, 32)
            }
        }
        .ignoresSafeArea(edges: .top)
        .scrollDismissesKeyboard(.interactively)
        .background(Brand.background)
        .toolbar(.hidden, for: .navigationBar)
        .toast($toast)
        .onAppear {
            if let notice = session.notice { toast = notice; session.notice = nil }
        }
        .alert("الدخول بـ\(Biometrics.name)", isPresented: $showOffer) {
            Button("تفعيل") { Task { await enableBiometric() } }
            Button("ليس الآن", role: .cancel) { finishLogin() }
        } message: {
            Text("هل تريد فتح التطبيق بـ\(Biometrics.name) في المرات القادمة بدل كلمة المرور؟")
        }
    }

    private func login() {
        guard !phone.isBlank, !password.isBlank else { toast = "يرجى إدخال رقم الهاتف وكلمة المرور"; return }
        loading = true
        Task {
            defer { loading = false }
            do {
                let user = try await API.login(phone: phone.trimmed, password: password)
                if Biometrics.isAvailable && !TokenStore.biometricLogin {
                    offerBiometricFor = user.role
                    showOffer = true
                } else {
                    session.signedIn(role: user.role)
                }
            } catch {
                toast = error.localizedDescription
            }
        }
    }

    private func enableBiometric() async {
        if await Biometrics.authenticate(reason: "تفعيل الدخول إلى وَثْب بـ\(Biometrics.name)") == nil {
            TokenStore.biometricLogin = true
        }
        finishLogin()
    }

    private func finishLogin() {
        guard let role = offerBiometricFor else { return }
        offerBiometricFor = nil
        session.signedIn(role: role)
    }
}

extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
    var isBlank: Bool { trimmed.isEmpty }
}
