import SwiftUI

/// «ملف المنشأة»: business details and the Jawwal Pay wallet wages are paid from.
struct BusinessProfileView: View {
    @State private var profile: BusinessProfile?
    @State private var error: String?
    @State private var legalName = ""
    @State private var tradeName = ""
    @State private var city = ""
    @State private var address = ""
    @State private var contactName = ""
    @State private var contactPhone = ""
    @State private var wallet = ""
    @State private var saving = false
    @State private var toast: String?
    @State private var deleting = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let profile {
                    Text("الهاتف: \(profile.phone.localPhone)").font(.wathb(15)).foregroundStyle(Brand.muted)
                    if let email = profile.email, !email.isEmpty {
                        Text("البريد: \(email)").font(.wathb(15)).foregroundStyle(Brand.muted)
                    }
                    StatusBadge(text: ownerLabel(profile.verificationStatus), color: ownerColor(profile.verificationStatus))

                    FormField(label: "الاسم القانوني", text: $legalName, contentType: .organizationName)
                    FormField(label: "الاسم التجاري", text: $tradeName)
                    FormField(label: "المدينة", text: $city, contentType: .addressCity)
                    FormField(label: "العنوان", text: $address, contentType: .streetAddressLine1)
                    FormField(label: "اسم المسؤول", text: $contactName, contentType: .name)
                    FormField(label: "هاتف التواصل", text: $contactPhone, keyboard: .phonePad, contentType: .telephoneNumber)
                    FormField(label: "رقم محفظة Jawwal Pay", text: $wallet, keyboard: .phonePad)
                    Text("تدفع منها أجور العمال. مثال: 0599123456").font(.wathb(12)).foregroundStyle(Brand.muted)
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
        .scrollDismissesKeyboard(.interactively)
        .background(Brand.background)
        .refreshable { await load() }
        .task { if profile == nil { await load() } }
        .navigationTitle("ملف المنشأة")
        .navigationBarTitleDisplayMode(.inline)
        .toast($toast)
    }

    private func ownerLabel(_ s: String) -> String {
        ["PENDING": "في انتظار التحقق", "APPROVED": "موثّق ✓", "REJECTED": "مرفوض", "SUSPENDED": "موقوف"][s] ?? StatusLabels.unmapped
    }

    private func ownerColor(_ s: String) -> Color {
        switch s {
        case "APPROVED": return Brand.primary
        case "PENDING": return Brand.secondary
        default: return Brand.error
        }
    }

    private func fill(_ p: BusinessProfile) {
        profile = p
        legalName = p.legalName; tradeName = p.tradeName; city = p.locationCity; address = p.locationAddress
        contactName = p.contactName; contactPhone = p.contactPhone; wallet = p.jawwalPayWallet?.localPhone ?? ""
    }

    private func load() async {
        do { fill(try await API.businessProfile()); error = nil }
        catch { if profile == nil { self.error = error.localizedDescription } }
    }

    private func save() {
        saving = true
        Task {
            defer { saving = false }
            do {
                fill(try await API.updateBusinessProfile(.init(
                    legalName: legalName.trimmed, tradeName: tradeName.trimmed, locationAddress: address.trimmed,
                    locationCity: city.trimmed, contactName: contactName.trimmed, contactPhone: contactPhone.trimmed,
                    jawwalPayWallet: wallet.filter { $0.isNumber || $0 == "+" }.asciiDigitsKeepingPlus)))
                toast = "تم حفظ ملف المنشأة"
            } catch {
                // e.g. «رقم محفظة Jawwal Pay غير صالح: …»
                toast = error.localizedDescription
            }
        }
    }
}

extension String {
    /// "٠٥٩٩…" or "+970…" → ASCII digits, keeping a leading "+".
    var asciiDigitsKeepingPlus: String {
        (hasPrefix("+") ? "+" : "") + asciiDigits
    }
}
