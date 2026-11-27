import SwiftUI

/// «الالتزامات المالية»: the business's wages, with «تحويل الأجر» while one is unpaid.
struct BusinessWagesView: View {
    @Environment(BusinessNav.self) private var nav
    @State private var wages: [WageObligation]?
    @State private var error: String?

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                if let wages {
                    if wages.isEmpty { MessageView(message: "لا توجد التزامات مالية حالياً") }
                    ForEach(wages) { card($0) }
                } else if let error {
                    MessageView(message: error, isError: true) { Task { await load() } }
                } else {
                    LoadingView().frame(height: 400)
                }
            }
            .padding(16)
        }
        .background(Brand.background)
        .refreshable { await load() }
        .onAppear { Task { await load() } }
        .navigationTitle("الالتزامات المالية")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func card(_ w: WageObligation) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                Text(w.jobTitle).font(.wathb(17, .medium))
                Spacer()
                StatusBadge(text: businessWageLabel(w.status), color: businessWageColor(w.status))
            }
            Text("العامل: \(w.workerName ?? w.workerPhone?.localPhone ?? "")").font(.wathb(13)).foregroundStyle(Brand.muted)
            Text(w.amountDisplay.arabicAmount).font(.wathb(20, .bold)).foregroundStyle(Brand.primary)
            Text("تاريخ الاستحقاق: \(ArabicFormat.date(w.dueDate))").font(.wathb(13)).foregroundStyle(Brand.muted)
            if ["PENDING", "DUE", "REJECTED"].contains(w.status) {
                Button("تحويل الأجر") { nav.open(.payment(w.id)) }.buttonStyle(PrimaryButtonStyle())
            }
        }
        .card()
    }

    private func load() async {
        do { wages = try await API.wages(); error = nil }
        catch { if wages == nil { self.error = error.localizedDescription } }
    }
}

func businessWageLabel(_ s: String) -> String {
    ["PENDING": "معلق", "DUE": "مستحق", "DECLARED": "تم الإعلان", "AWAITING_ACK": "بانتظار التأكيد",
     "UNDER_REVIEW": "قيد المراجعة", "DISPUTED": "متنازع عليه", "VERIFIED_PAID": "مدفوع ومؤكد",
     "REJECTED": "مرفوض", "CANCELLED": "ملغى"][s] ?? StatusLabels.unmapped
}

func businessWageColor(_ s: String) -> Color {
    switch s {
    case "PENDING", "UNDER_REVIEW": return Brand.secondary
    case "DUE", "REJECTED", "DISPUTED", "CANCELLED": return Brand.error
    case "DECLARED", "AWAITING_ACK": return Brand.primary
    case "VERIFIED_PAID": return Brand.tertiary
    default: return Brand.muted
    }
}

// MARK: - «تحويل الأجر»

/// From the business's Jawwal Pay wallet straight to the worker's; Wathb never holds the money.
/// Everything shown comes from the server, and the SMS code is sent once and never kept.
struct WagePaymentView: View {
    let wageId: String
    @Environment(BusinessNav.self) private var nav

    @State private var info: PaymentInfo?
    @State private var loading = true
    @State private var busy = false
    @State private var error: String?
    @State private var timeout = false
    @State private var resendAt: Date?
    @State private var code = ""
    @State private var reference = ""
    @State private var confirmManual = false
    @State private var copied: String?

    private var paid: Bool { ["AWAITING_ACK", "VERIFIED_PAID"].contains(info?.status ?? "") }
    private var codeSent: Bool { info?.payable == true && info?.attempt?.status == "INITIATED" }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if loading {
                    LoadingView().frame(height: 300)
                } else if let info {
                    summary(info)
                    if paid {
                        paidSection(info)
                    } else if !info.payable {
                        Text("حالة الأجر: \(businessWageLabel(info.status))").font(.wathb(16))
                    } else if info.mode == "manual" {
                        manualSection(info)
                    } else if info.needsWallet {
                        Text("لتحويل الأجر من وَثْب اربط محفظة Jawwal Pay في ملف المنشأة أولًا.").font(.wathb(16))
                        Button("ربط المحفظة") { nav.open(.profile) }.buttonStyle(PrimaryButtonStyle())
                    } else {
                        automaticSection(info)
                    }
                    if let error { Text(error).font(.wathb(15)).foregroundStyle(Brand.error) }
                } else {
                    MessageView(message: error ?? "تعذّر التحميل", isError: true) { Task { await load() } }
                }
            }
            .padding(16)
        }
        .background(Brand.background)
        .refreshable { await load() }
        .task { await load() }
        .navigationTitle("تحويل الأجر")
        .navigationBarTitleDisplayMode(.inline)
        .toast($copied)
        .alert("حوّلت الأجر؟", isPresented: $confirmManual) {
            Button("نعم، حوّلت") { declare() }
            Button("إلغاء", role: .cancel) {}
        } message: {
            if let info {
                Text("هل حوّلت \(info.amountDisplay.arabicAmount) إلى محفظة العامل \(info.workerWallet.localPhone)؟ سيؤكد العامل الاستلام من جهته.")
            }
        }
    }

    // MARK: Sections

    private func summary(_ info: PaymentInfo) -> some View {
        let showCopy = info.mode == "manual" && !paid
        return VStack(alignment: .leading, spacing: 10) {
            Text(info.jobTitle).font(.wathb(17, .bold))
            summaryRow("العامل", info.workerName.isBlank ? "—" : info.workerName)
            summaryRow("محفظة العامل في Jawwal Pay", info.workerWallet.localPhone,
                       copy: showCopy ? info.workerWallet.localPhone : nil)
            summaryRow("المبلغ المتفق عليه", info.amountDisplay.arabicAmount, emphasize: true,
                       copy: showCopy ? plainAmount(info.amount) : nil)
        }
        .card()
    }

    private func summaryRow(_ label: String, _ value: String, emphasize: Bool = false, copy: String? = nil) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(.wathb(13)).foregroundStyle(Brand.muted)
                Text(value).font(.wathb(emphasize ? 22 : 17, emphasize ? .bold : .regular))
                    .foregroundStyle(emphasize ? Brand.primary : .primary)
            }
            Spacer()
            if let copy {
                Button {
                    UIPasteboard.general.string = copy
                    copied = "نُسخ: \(copy)"
                } label: { Image(systemName: "doc.on.doc") }
                .accessibilityLabel("نسخ \(label)")
            }
        }
    }

    /// "8500" agorot → "85" / "85.50": what the business types in its Jawwal Pay app.
    private func plainAmount(_ agorot: Int) -> String {
        agorot % 100 == 0 ? String(agorot / 100) : String(format: "%d.%02d", agorot / 100, agorot % 100)
    }

    @ViewBuilder private func manualSection(_ info: PaymentInfo) -> some View {
        Text("١. افتح تطبيق Jawwal Pay وحوّل المبلغ إلى محفظة العامل. استعمل زرّي النسخ.").font(.wathb(15))
        Text("٢. ارجع إلى وَثْب، اكتب رقم العملية واضغط «حوّلت الأجر».").font(.wathb(15))
        FormField(label: "رقم العملية في Jawwal Pay", text: $reference)
        Text("مطلوب: تجده في رسالة Jawwal Pay أو في سجل العمليات.").font(.wathb(12)).foregroundStyle(Brand.muted)
        // The server refuses a declaration without the Jawwal Pay transaction number.
        LoadingButton(title: "حوّلت الأجر", loading: busy) { confirmManual = true }
            .disabled(reference.isBlank)
    }

    @ViewBuilder private func automaticSection(_ info: PaymentInfo) -> some View {
        if let wallet = info.businessWallet {
            Text("من محفظتك: \(wallet.localPhone)").font(.wathb(14)).foregroundStyle(Brand.muted)
        }
        if timeout || info.attempt?.status == "UNKNOWN" {
            Text("لم يصل رد من Jawwal Pay. لن نرسل تحويلًا جديدًا قبل أن نعرف ما حدث للسابق.").font(.wathb(15))
            Button("تحقق من حالة التحويل") { Task { await load() } }.buttonStyle(OutlineButtonStyle()).disabled(busy)
        } else if !codeSent {
            Text("سيصلك رمز في رسالة من Jawwal Pay لتأكيد التحويل.").font(.wathb(15))
            LoadingButton(title: "إرسال", loading: busy, action: send)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                Text("رمز التأكيد").font(.wathb(14, .medium)).foregroundStyle(Brand.muted)
                // iOS offers the code from the Jawwal Pay message above the keyboard.
                TextField("", text: $code)
                    .font(.wathb(22, .bold))
                    .keyboardType(.numberPad)
                    .textContentType(.oneTimeCode)
                    .onChange(of: code) { _, v in code = String(v.asciiDigits.prefix(8)) }
                    .fieldBox()
                Text("يظهر الرمز فوق لوحة المفاتيح عند وصول الرسالة، أو اكتبه بنفسك.").font(.wathb(12)).foregroundStyle(Brand.muted)
            }
            LoadingButton(title: "تأكيد التحويل", loading: busy, action: confirm)
                .disabled(code.count < 4)
            TimelineView(.periodic(from: .now, by: 1)) { context in
                let wait = max(0, Int((resendAt ?? .distantPast).timeIntervalSince(context.date).rounded(.up)))
                Button(wait > 0 ? "إعادة إرسال الرمز بعد \(wait.arabic) ثانية" : "إعادة إرسال الرمز", action: send)
                    .font(.wathb(15)).disabled(busy || wait > 0)
                    .frame(maxWidth: .infinity)
            }
        }
    }

    @ViewBuilder private func paidSection(_ info: PaymentInfo) -> some View {
        let automatic = info.mode == "automatic"
        Text(automatic ? "✓ تم تحويل الأجر إلى محفظة العامل." : "✓ سجّلنا أنك حوّلت الأجر.")
            .font(.wathb(17, .bold)).foregroundStyle(Brand.tertiary)
        Text(automatic ? "أبلغنا العامل. إن لم يصله الأجر يمكنه الاعتراض خلال ٢٤ ساعة." : "سيؤكد العامل الاستلام من جهته.")
            .font(.wathb(15))
        Button("رجوع") { nav.back() }.buttonStyle(PrimaryButtonStyle())
    }

    // MARK: Actions

    private func load() async {
        do { apply(try await API.payment(wageId)); error = nil }
        catch { if info == nil { self.error = error.localizedDescription } }
        loading = false
    }

    private func send() { run { try await API.initiatePayment(wageId) } }

    private func confirm() {
        let digits = code.asciiDigits
        guard digits.count >= 4 else { error = "أدخل الرمز كما وصلك في الرسالة."; return }
        code = ""
        run { try await API.confirmPayment(wageId, code: digits) }
    }

    private func declare() {
        let ref = reference.trimmed
        run {
            try await API.declarePayment(wageId, reference: ref)
            return try await API.payment(wageId)
        }
    }

    private func run(_ block: @escaping () async throws -> PaymentInfo) {
        guard !busy else { return }
        busy = true
        error = nil
        timeout = false
        Task {
            defer { busy = false }
            do {
                apply(try await block())
            } catch let e as APIError {
                error = e.message
                timeout = e.status == 504
                if let wait = e.field("retry_after") as? Int { resendAt = Date().addingTimeInterval(TimeInterval(wait)) }
                // Re-read the server's view (attempt failed, already paid, …) but keep the message.
                if let fresh = try? await API.payment(wageId) { apply(fresh) }
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private func apply(_ fresh: PaymentInfo) {
        info = fresh
        if let at = fresh.attempt?.resendAvailableAt, let date = ISO8601DateFormatter.flexible(at) { resendAt = date }
    }
}

extension ISO8601DateFormatter {
    /// Django sends fractional seconds sometimes, not always.
    static func flexible(_ s: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: s) { return d }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: s)
    }
}
