import SwiftUI

/// «الاعتراضات» (android AdminDisputesScreen): unpaid wages to chase, wages awaiting the
/// worker's acknowledgement, and wage disputes to settle.
struct AdminDisputesView: View {
    @State private var disputes: [Dispute]?
    @State private var unpaid: [WageObligation] = []
    @State private var stale: [WageObligation] = []
    @State private var error: String?
    @State private var toast: String?
    @State private var settle: SettleTarget?
    @State private var callResult: WageObligation?
    @Environment(\.openURL) private var openURL

    struct SettleTarget: Identifiable {
        let dispute: Dispute
        /// verify / reject / resolve
        let action: String
        var id: String { dispute.id + action }
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 10) {
                if !unpaid.isEmpty {
                    header("أجور لم تُدفع منذ ٣ أيام", color: Brand.error)
                    ForEach(unpaid) { unpaidCard($0) }
                    Divider().padding(.vertical, 4)
                }
                if !stale.isEmpty {
                    header("بانتظار إقرار العامل")
                    ForEach(stale) { staleCard($0) }
                    Divider().padding(.vertical, 4)
                }
                if let disputes {
                    if disputes.isEmpty { MessageView(message: "لا توجد نزاعات أجور مفتوحة") }
                    ForEach(disputes) { disputeCard($0) }
                } else if let error {
                    MessageView(message: error, isError: true) { Task { await load() } }
                } else {
                    LoadingView().frame(height: 300)
                }
            }
            .padding(16)
        }
        .background(Brand.background)
        .refreshable { await load() }
        .task { await load() }
        .navigationTitle("نزاعات الأجور")
        .navigationBarTitleDisplayMode(.inline)
        .toast($toast)
        .sheet(item: $settle) { target in
            NotesSheet(title: settleTitle(target.action), message: settleConsequence(target.action),
                       subtitle: "المبلّغ: \(target.dispute.raisedByPhone.localPhone)") { _, notes in
                if target.action == "resolve" {
                    _ = try await API.resolveDispute(target.dispute.id, notes: notes)
                } else {
                    try await API.settleWage(target.dispute, action: target.action, notes: notes)
                }
                toast = "تم تحديث النزاع بنجاح"
                await load()
            }
        }
        .sheet(item: $callResult) { wage in
            // «نتيجة المكالمة»: the worker confirmed or denied receiving the wage by phone.
            NotesSheet(title: "نتيجة المكالمة", message: "اختر ما قاله العامل ثم اكتب ملاحظات المكالمة.",
                       subtitle: "\(wage.workerName ?? wage.workerPhone?.localPhone ?? "") — \(wage.amountDisplay.arabicAmount)",
                       choices: [("confirmed_by_phone", "أكّد الاستلام"), ("disputed_by_phone", "نفى الاستلام")]) { action, notes in
                _ = try await API.phoneResolveWage(wage.id, action: action, notes: notes)
                toast = "تم تسجيل قرار المكالمة"
                await load()
            }
        }
    }

    private func header(_ text: String, color: Color = .primary) -> some View {
        Text(text).font(.wathb(17, .bold)).foregroundStyle(color)
    }

    /// Due 3+ days with no payment declared: call the business.
    private func unpaidCard(_ w: WageObligation) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(w.businessName ?? "صاحب العمل").font(.wathb(16, .medium))
                    Text("العامل: \(w.workerName ?? w.workerPhone?.localPhone ?? "")").font(.wathb(13)).foregroundStyle(Brand.muted)
                }
                Spacer()
                callButton(w.businessPhone, label: "اتصل بصاحب العمل")
            }
            Text(w.jobTitle).font(.wathb(15))
            Text(w.amountDisplay.arabicAmount).font(.wathb(18, .bold)).foregroundStyle(Brand.error)
            Text("مستحق منذ: \(ArabicFormat.date(w.dueDate))").font(.wathb(13)).foregroundStyle(Brand.muted)
        }
        .card()
    }

    private func staleCard(_ w: WageObligation) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(w.workerName ?? w.workerPhone?.localPhone ?? "").font(.wathb(16, .medium))
                    Text(w.workerPhone?.localPhone ?? "").font(.wathb(13)).foregroundStyle(Brand.muted)
                }
                Spacer()
                callButton(w.workerPhone, label: "اتصل")
            }
            Text(w.jobTitle).font(.wathb(15))
            Text(w.amountDisplay.arabicAmount).font(.wathb(18, .bold)).foregroundStyle(Brand.primary)
            Text("تاريخ الإعلان: \(w.declarations?.first.map { ArabicFormat.date($0.declaredAt) } ?? "—")")
                .font(.wathb(13)).foregroundStyle(Brand.muted)
            Button("تسجيل نتيجة المكالمة") { callResult = w }.buttonStyle(PrimaryButtonStyle())
        }
        .card()
    }

    private func disputeCard(_ d: Dispute) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                Text(d.raisedByPhone.localPhone).font(.wathb(16, .medium))
                Spacer()
                StatusBadge(text: AdminLabels.dispute(d.status), color: disputeColor(d.status))
            }
            Text(d.description).font(.wathb(15))
            Text("تاريخ الرفع: \(ArabicFormat.date(d.createdAt))").font(.wathb(13)).foregroundStyle(Brand.muted)
            if let notes = d.resolutionNotes, !notes.isBlank {
                Text("ملاحظات: \(notes)").font(.wathb(13)).foregroundStyle(Brand.muted)
            }
            if d.canSettleWage {
                HStack(spacing: 8) {
                    Button("الدفع تم") { settle = .init(dispute: d, action: "verify") }.buttonStyle(PrimaryButtonStyle())
                    Button("الدفع لم يتم") { settle = .init(dispute: d, action: "reject") }
                        .buttonStyle(OutlineButtonStyle(color: Brand.error))
                }
            } else if ["OPEN", "IN_REVIEW"].contains(d.status) {
                Button("حل النزاع") { settle = .init(dispute: d, action: "resolve") }.buttonStyle(OutlineButtonStyle())
            }
        }
        .card()
    }

    @ViewBuilder private func callButton(_ phone: String?, label: String) -> some View {
        if let phone, !phone.isEmpty, let url = Contact.call(phone) {
            Button { openURL(url) } label: { Image(systemName: "phone.fill").font(.title3) }
                .accessibilityLabel(label)
        }
    }

    private func disputeColor(_ s: String) -> Color {
        switch s {
        case "OPEN": return Brand.error
        case "IN_REVIEW": return Brand.secondary
        case "RESOLVED": return Brand.tertiary
        default: return Brand.muted
        }
    }

    private func settleTitle(_ action: String) -> String {
        switch action {
        case "verify": return "تأكيد: الدفع تم"
        case "reject": return "تأكيد: الدفع لم يتم"
        default: return "تأكيد: حل النزاع"
        }
    }

    private func settleConsequence(_ action: String) -> String {
        switch action {
        case "verify": return "سيُسجَّل الأجر مدفوعًا ويُغلق النزاع."
        case "reject": return "سيعود الأجر مستحقًا، وعلى صاحب العمل أن يدفع ويعلن الدفع من جديد."
        default: return "سيُغلق النزاع بهذه الملاحظة."
        }
    }

    private func load() async {
        async let d = API.wageDisputes()
        async let u = try? API.unpaidWages()
        async let s = try? API.staleWages()
        do { disputes = try await d; error = nil }
        catch { if disputes == nil { self.error = error.localizedDescription } }
        unpaid = await u ?? unpaid
        stale = await s ?? stale
    }
}

/// A required note (and, when `choices` is set, one of them), then the action. Errors stay on the sheet.
struct NotesSheet: View {
    let title: String
    let message: String
    var subtitle: String?
    var choices: [(value: String, label: String)] = []
    let onConfirm: (_ choice: String, _ notes: String) async throws -> Void
    @State private var choice = ""
    @State private var notes = ""
    @State private var busy = false
    @State private var error: String?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 12) {
                if let subtitle { Text(subtitle).font(.wathb(15)) }
                Text(message).font(.wathb(14)).foregroundStyle(Brand.muted)
                if !choices.isEmpty {
                    Picker("", selection: $choice) {
                        ForEach(choices, id: \.value) { Text($0.label).tag($0.value) }
                    }
                    .pickerStyle(.segmented)
                }
                FormField(label: "ملاحظات (مطلوبة)", text: $notes)
                Text("لا تكتب اسمًا أو رقم هاتف في الملاحظة").font(.wathb(12)).foregroundStyle(Brand.muted)
                if let error { Text(error).font(.wathb(14)).foregroundStyle(Brand.error) }
                LoadingButton(title: "تأكيد", loading: busy) {
                    busy = true
                    Task {
                        defer { busy = false }
                        do { try await onConfirm(choice, notes.trimmed); dismiss() }
                        catch { self.error = error.localizedDescription }
                    }
                }
                .disabled(notes.isBlank)
                Spacer()
            }
            .padding(20)
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("إلغاء") { dismiss() } } }
            .onAppear { if choice.isEmpty { choice = choices.first?.value ?? "" } }
        }
        .environment(\.layoutDirection, .rightToLeft)
        .presentationDetents([.medium, .large])
    }
}
