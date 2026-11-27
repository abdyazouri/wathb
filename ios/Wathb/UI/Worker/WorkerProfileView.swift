import SwiftUI

/// «حسابي»: profile fields, Face ID login, logout and account deletion.
struct WorkerProfileView: View {
    @State private var profile: WorkerProfile?
    @State private var error: String?
    @State private var fullName = ""
    @State private var city = ""
    @State private var region = ""
    @State private var available = true
    @State private var saving = false
    @State private var toast: String?
    @State private var deleting = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let profile {
                    Text("الهاتف: \(profile.phone.localPhone)").font(.wathb(15)).foregroundStyle(Brand.muted)
                    if profile.isVerified {
                        Text("موثّق ✓").font(.wathb(13, .medium)).foregroundStyle(Brand.primary)
                    }
                    FormField(label: "الاسم الكامل", text: $fullName, contentType: .name)
                    FormField(label: "المدينة", text: $city, contentType: .addressCity)
                    FormField(label: "المنطقة / الحي", text: $region)
                    Toggle("متاح للعمل", isOn: $available).font(.wathb(16)).tint(Brand.primary)
                    LoadingButton(title: "حفظ", loading: saving, action: save).padding(.top, 4)
                } else if let error {
                    MessageView(message: error, isError: true) { Task { await load() } }
                } else {
                    LoadingView().frame(height: 300)
                }

                AccountSection(deleting: $deleting, toast: $toast)
            }
            .padding(16)
        }
        .background(Brand.background)
        .refreshable { await load() }
        .task { if profile == nil { await load() } }
        .navigationTitle("ملفي الشخصي")
        .navigationBarTitleDisplayMode(.inline)
        .toast($toast)
    }

    private func load() async {
        do {
            let p = try await API.workerProfile()
            profile = p
            fullName = p.fullName; city = p.locationCity; region = p.locationRegion; available = p.isAvailable
            error = nil
        } catch {
            if profile == nil { self.error = error.localizedDescription }
        }
    }

    private func save() {
        saving = true
        Task {
            defer { saving = false }
            do {
                profile = try await API.updateWorkerProfile(.init(fullName: fullName.trimmed, locationCity: city.trimmed,
                                                                  locationRegion: region.trimmed, isAvailable: available))
                toast = "تم حفظ الملف الشخصي"
            } catch {
                toast = error.localizedDescription
            }
        }
    }
}

/// Face ID login switch, «تسجيل الخروج» and «حذف حسابي» (shared by every role's account screen).
struct AccountSection: View {
    @Binding var deleting: Bool
    @Binding var toast: String?
    @State private var biometric = TokenStore.biometricLogin
    @State private var password = ""
    @State private var deleteBusy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if Biometrics.isAvailable || biometric {
                Toggle(isOn: Binding(get: { biometric }, set: { turnOn in Task { await setBiometric(turnOn) } })) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("الدخول بـ\(Biometrics.name)").font(.wathb(16))
                        Text("عند فتح التطبيق بدل كلمة المرور").font(.wathb(13)).foregroundStyle(Brand.muted)
                    }
                }
                .tint(Brand.primary)
                .padding(.top, 8)
            }

            Button { Task { await Session.shared.logout() } } label: {
                Label("تسجيل الخروج", systemImage: "rectangle.portrait.and.arrow.right")
            }
            .buttonStyle(OutlineButtonStyle(color: Brand.error))

            Button("حذف حسابي") { password = ""; deleting = true }
                .buttonStyle(OutlineButtonStyle(color: Brand.error))
                .disabled(deleteBusy)
        }
        .alert("تأكيد حذف الحساب", isPresented: $deleting) {
            SecureField("كلمة المرور للتأكيد", text: $password)
            Button("احذف حسابي", role: .destructive) { delete() }
            Button("إلغاء", role: .cancel) { password = "" }
        } message: {
            Text("سيُحذف حسابك وجميع بياناتك الشخصية نهائياً. تبقى سجلات الأجور والمهام بدون اسم للأغراض المحاسبية. لا يمكن التراجع عن هذا الإجراء.")
        }
    }

    /// Turning it on needs one successful Face ID / passcode check.
    private func setBiometric(_ on: Bool) async {
        if !on {
            TokenStore.biometricLogin = false
            biometric = false
        } else if await Biometrics.authenticate(reason: "تفعيل الدخول إلى وَثْب بـ\(Biometrics.name)") == nil {
            TokenStore.biometricLogin = true
            biometric = true
        }
    }

    private func delete() {
        let pwd = password
        password = ""
        guard !pwd.isEmpty else { toast = "أدخل كلمة المرور للتأكيد"; return }
        deleteBusy = true
        Task {
            defer { deleteBusy = false }
            do {
                try await API.deleteAccount(password: pwd)
                Session.shared.accountDeleted()
            } catch {
                toast = error.localizedDescription
            }
        }
    }
}
