import SwiftUI

// Same consent text and version as android ConsentScreen.kt (the server records the version).
private let consentVersion = 1

private let consentText = """
شروط الاستخدام وسياسة الخصوصية — وَثْب

باستخدامك لتطبيق وَثْب، فإنك توافق على ما يلي:

١. جمع البيانات
نجمع رقم هاتفك وبيانات ملفك الشخصي وسجل عملك على المنصة. قد نجمع رقم هويتك الوطنية عند التحقق منك، ويُخزَّن مشفَّراً ولا يُكشف عنه.

٢. استخدام البيانات
تُستخدم بياناتك لمطابقتك بأصحاب العمل، وإدارة المدفوعات، وتحسين الخدمة، وضمان سلامة المنصة.

٣. حماية بياناتك
لا نبيع بياناتك ولا نشاركها مع أطراف خارجية لأغراض تجارية.

٤. حقوقك
يحق لك طلب حذف حسابك وبياناتك في أي وقت عبر التواصل مع الدعم.

٥. التعديلات
قد نُحدِّث هذه الشروط ونُخطرك بأي تغييرات جوهرية.

بالمتابعة، تؤكد أنك قرأت هذه الشروط وتوافق عليها.
"""

struct ConsentView: View {
    let onAccepted: (Int) -> Void
    @State private var checked = false

    var body: some View {
        VStack(spacing: 16) {
            ScrollView {
                Text(consentText).font(.wathb(15)).frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 8)
            }
            Button { checked.toggle() } label: {
                HStack {
                    Image(systemName: checked ? "checkmark.square.fill" : "square").font(.title3)
                    Text("قرأت الشروط وأوافق عليها").font(.wathb(15))
                    Spacer()
                }
                .foregroundStyle(checked ? Brand.primary : .primary)
            }
            Button("أكمل التسجيل") { onAccepted(consentVersion) }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(!checked)
        }
        .padding(24)
        .background(Brand.background)
        .navigationTitle("الشروط والأحكام")
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct RegisterView: View {
    let consentVersion: Int
    let onLogin: () -> Void

    @State private var role = "WORKER"
    @State private var phone = ""
    @State private var password = ""
    @State private var fullName = ""
    @State private var legalName = ""
    @State private var contactName = ""
    @State private var contactPhone = ""
    @State private var loading = false
    @State private var toast: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("نوع الحساب").font(.wathb(16, .medium))
                Picker("نوع الحساب", selection: $role) {
                    Text("عامل").tag("WORKER")
                    Text("منشأة").tag("BUSINESS")
                }
                .pickerStyle(.segmented)

                FormField(label: "رقم الهاتف", text: $phone, keyboard: .phonePad, contentType: .username)
                PasswordField(text: $password, contentType: .newPassword)
                if role == "WORKER" {
                    FormField(label: "الاسم الكامل", text: $fullName, contentType: .name)
                } else {
                    FormField(label: "الاسم التجاري الرسمي", text: $legalName, contentType: .organizationName)
                    FormField(label: "اسم جهة الاتصال", text: $contactName, contentType: .name)
                    FormField(label: "هاتف جهة الاتصال", text: $contactPhone, keyboard: .phonePad, contentType: .telephoneNumber)
                }
                LoadingButton(title: "تسجيل", loading: loading, action: register).padding(.top, 8)
                Button("لديك حساب بالفعل؟ سجّل الدخول", action: onLogin)
                    .font(.wathb(15)).foregroundStyle(Brand.primary)
                    .frame(maxWidth: .infinity)
            }
            .padding(24)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Brand.background)
        .navigationTitle("إنشاء حساب")
        .navigationBarTitleDisplayMode(.inline)
        .toast($toast)
    }

    private func register() {
        let worker = role == "WORKER"
        let missing = phone.isBlank || password.isBlank ||
            (worker ? fullName.isBlank : legalName.isBlank || contactName.isBlank || contactPhone.isBlank)
        guard !missing else { toast = "يرجى ملء جميع الحقول المطلوبة"; return }
        loading = true
        Task {
            defer { loading = false }
            do {
                let user = worker
                    ? try await API.registerWorker(.init(phone: phone.trimmed, password: password,
                                                         fullName: fullName.trimmed, consentVersion: consentVersion))
                    : try await API.registerBusiness(.init(phone: phone.trimmed, password: password,
                                                           legalName: legalName.trimmed, contactName: contactName.trimmed,
                                                           contactPhone: contactPhone.trimmed, consentVersion: consentVersion))
                Session.shared.signedIn(role: user.role)
            } catch {
                toast = error.localizedDescription
            }
        }
    }
}

/// Shown on launch when the user turned on Face ID login. The saved session is used only
/// after the check passes; the only other way in is signing in again with the password.
struct UnlockView: View {
    @State private var error: String?
    private let available = Biometrics.isAvailable

    var body: some View {
        VStack(spacing: 20) {
            Spacer()
            Text("وَثْب").font(.wathb(44, .black)).foregroundStyle(Brand.primary)
            if available {
                Image(systemName: Biometrics.systemImage).font(.system(size: 64)).foregroundStyle(Brand.primary)
                Text("افتح التطبيق بـ\(Biometrics.name)").font(.wathb(17, .medium)).multilineTextAlignment(.center)
                if let error { Text(error).font(.wathb(14)).foregroundStyle(Brand.error).multilineTextAlignment(.center) }
                Button("الدخول بـ\(Biometrics.name)") { Task { await unlock() } }
                    .buttonStyle(PrimaryButtonStyle())
            } else {
                Text("لا يوجد Face ID ولا رمز قفل على الهاتف الآن، فادخل بكلمة المرور.")
                    .font(.wathb(16)).multilineTextAlignment(.center)
            }
            Button("الدخول بكلمة المرور") {
                // Leave the saved session entirely; the password login starts a new one.
                Task { await Session.shared.logout() }
            }
            .font(.wathb(15)).foregroundStyle(Brand.primary)
            Spacer()
        }
        .padding(24)
        .background(Brand.background)
        .task { if available { await unlock() } }
    }

    private func unlock() async {
        error = nil
        if let message = await Biometrics.authenticate(reason: "الدخول إلى وَثْب") {
            error = message
        } else {
            Session.shared.unlocked()
        }
    }
}
