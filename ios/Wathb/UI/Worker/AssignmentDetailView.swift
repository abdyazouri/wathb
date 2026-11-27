import SwiftUI

/// «تفاصيل المهمة»: contact the business, check in, finish the job, confirm or dispute what the
/// business recorded, acknowledge the wage, cancel before the work day.
struct AssignmentDetailView: View {
    @State private var assignment: Assignment
    @State private var attendance: [Attendance]?
    @State private var completion: Completion?
    @State private var completionLoaded = false
    @State private var wage: WageObligation?
    @State private var busy = false
    @State private var toast: String?
    @State private var gate = AcknowledgeGate()

    @State private var finishing = false
    @State private var hours = ""
    @State private var notes = ""
    @State private var cancelling = false
    @State private var cancelReason = ""
    @State private var disputing = false
    @State private var disputeReason = ""
    @Environment(\.openURL) private var openURL

    init(initial: Assignment) { _assignment = State(initialValue: initial) }

    private var a: Assignment { assignment }
    private var today: String { Gaza.today() }

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                if let phone = a.businessPhone, !phone.isEmpty { contactCard(phone) }
                statusCard
                if a.canWorkerCancel(today: today) {
                    Button("إلغاء المهمة") { cancelReason = ""; cancelling = true }
                        .buttonStyle(OutlineButtonStyle(color: Brand.error)).disabled(busy)
                }
            }
            .padding(16)
        }
        .background(Brand.background)
        .refreshable { await load() }
        .task { await load() }
        .navigationTitle("تفاصيل المهمة")
        .navigationBarTitleDisplayMode(.inline)
        .toast($toast)
        .acknowledgeGate(gate) { id, password in
            perform("تم تأكيد الاستلام") { wage = try await API.acknowledge(id, password: password) }
        }
        .alert("أتممت يوم عملي واطلب أجري", isPresented: $finishing) {
            TextField("ساعات العمل (اختياري)", text: $hours).keyboardType(.decimalPad)
            TextField("ملاحظات (اختياري)", text: $notes)
            Button("إرسال الطلب") {
                let h = hours.asciiDigitsKeepingDot
                perform("أُرسل طلب أجرك") {
                    completion = try await API.requestWage(a.id, hoursWorked: h.isEmpty ? nil : h, notes: notes.trimmed)
                }
            }
            Button("إلغاء", role: .cancel) {}
        } message: {
            Text("سيصل طلب أجرك إلى صاحب العمل الآن. إن لم يرد خلال ٢٤ ساعة يتأكد إتمام العمل تلقائيًا ويصبح أجرك مستحقًا.")
        }
        .alert("إلغاء المهمة", isPresented: $cancelling) {
            TextField("سبب الإلغاء (مطلوب)", text: $cancelReason)
            Button("تأكيد الإلغاء", role: .destructive) {
                guard !cancelReason.isBlank else { toast = "اكتب سبب الإلغاء"; return }
                let reason = cancelReason.trimmed
                perform { assignment = try await API.cancel(a.id, reason: reason) }
            }
            Button("تراجع", role: .cancel) {}
        } message: {
            Text("هل أنت متأكد أنك تريد إلغاء هذه المهمة؟")
        }
        .wageDisputeAlert(isPresented: $disputing, reason: $disputeReason, amount: wage?.amountDisplay) {
            guard let wage else { return }
            let reason = disputeReason
            perform("أُرسل اعتراضك") { self.wage = try await API.disputePayment(wage.id, description: reason) }
        }
    }

    // MARK: Cards

    private func contactCard(_ phone: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("صاحب العمل").font(.wathb(13, .medium)).foregroundStyle(Brand.muted)
            Text(phone.localPhone).font(.wathb(17, .medium)).environment(\.layoutDirection, .leftToRight)
            HStack(spacing: 8) {
                Button { if let u = Contact.call(phone) { openURL(u) } } label: { Label("اتصال", systemImage: "phone") }
                    .buttonStyle(OutlineButtonStyle())
                Button { if let u = Contact.whatsapp(phone) { openURL(u) } } label: { Label("واتساب", systemImage: "message") }
                    .buttonStyle(OutlineButtonStyle())
            }
        }
        .card()
    }

    private var statusCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("حالة المهمة").font(.wathb(13, .medium)).foregroundStyle(Brand.muted)
            switch a.status {
            case "OFFERED":
                Text("اختارك صاحب العمل — أكّد حضورك من «طلباتي»").font(.wathb(16))
            case "ACCEPTED", "ACTIVE":
                // The work section (check-in, «أتممت يوم عملي واطلب أجري») opens on the work day.
                if !a.workDayReached(today: today) {
                    Text("مقبولة — تبدأ \(ArabicFormat.date(a.jobWorkDate)) الساعة \(ArabicFormat.time(a.jobStartTime))")
                        .font(.wathb(16)).foregroundStyle(Brand.tertiary)
                } else {
                    workSection
                }
            case "COMPLETED":
                wageSection
            case "CANCELLED":
                Text("ملغاة").font(.wathb(16)).foregroundStyle(Brand.error)
            case "DECLINED":
                Text("مرفوضة").font(.wathb(16)).foregroundStyle(Brand.muted)
            default:
                Text(StatusLabels.label(StatusLabels.assignment, a.status)).font(.wathb(16)).foregroundStyle(Brand.muted)
            }
        }
        .card()
    }

    @ViewBuilder private var workSection: some View {
        let records = attendance ?? []
        Text("العمل جارٍ").font(.wathb(16, .bold)).foregroundStyle(Brand.primary)

        Text("الحضور").font(.wathb(14, .medium))
        ForEach(records) { r in
            let mine = r.submittedByPhone == a.workerPhone
            Text("\(ArabicFormat.date(r.workDate)) — \(StatusLabels.label(StatusLabels.attendance, r.status))\(mine ? "" : " (سجّله صاحب العمل)")")
                .font(.wathb(15))
            if !mine && r.status == "SUBMITTED" {
                confirmOrDispute(
                    confirm: { perform { _ = try await API.confirmAttendance(a.id, record: r.id); attendance = try await API.attendance(a.id) } },
                    dispute: { perform { _ = try await API.disputeAttendance(a.id, record: r.id); attendance = try await API.attendance(a.id) } })
            }
        }
        if attendance != nil && records.isEmpty {
            Text("لم يُسجَّل حضور بعد.").font(.wathb(13)).foregroundStyle(Brand.muted)
        }
        if attendance != nil, completion == nil, completionLoaded, !records.contains(where: { $0.workDate.prefix(10) == today }) {
            Button("سجّل حضوري اليوم") {
                perform { _ = try await API.checkIn(a.id, workDate: today); attendance = try await API.attendance(a.id) }
            }
            .buttonStyle(OutlineButtonStyle()).disabled(busy)
        }

        Divider()

        Text("إنهاء المهمة").font(.wathb(14, .medium))
        if !completionLoaded {
            ProgressView()
        } else if let completion {
            completionStatus(completion)
        } else {
            Text("عند انتهاء الشغل اضغط «أتممت يوم عملي واطلب أجري». يؤكد صاحب العمل، وإن لم يرد خلال ٢٤ ساعة يتأكد تلقائيًا.")
                .font(.wathb(13)).foregroundStyle(Brand.muted)
            Button("أتممت يوم عملي واطلب أجري") { hours = ""; notes = ""; finishing = true }
                .buttonStyle(PrimaryButtonStyle()).disabled(busy)
        }
    }

    @ViewBuilder private func completionStatus(_ c: Completion) -> some View {
        let mine = c.submittedByPhone == a.workerPhone
        switch c.status {
        case "SUBMITTED":
            if mine {
                Text("✓ أرسلت طلب أجرك. بانتظار صاحب العمل، ويتأكد تلقائيًا بعد ٢٤ ساعة إن لم يرد.").font(.wathb(15))
            } else {
                Text("سجّل صاحب العمل أن المهمة انتهت. هل هذا صحيح؟").font(.wathb(15))
                confirmOrDispute(
                    confirm: { perform { completion = try await API.confirmCompletion(a.id); await reloadAssignmentAndWage() } },
                    dispute: { perform { completion = try await API.disputeCompletion(a.id) } })
            }
        case "CONFIRMED":
            Text("✓ تم تأكيد إنهاء المهمة.").font(.wathb(15)).foregroundStyle(Brand.tertiary)
        case "DISPUTED":
            Text("تم الاعتراض على إتمام العمل، والنزاع لدى مشرف وَثْب.").font(.wathb(15)).foregroundStyle(Brand.error)
        default:
            Text(StatusLabels.label(StatusLabels.completion, c.status)).font(.wathb(15))
        }
    }

    @ViewBuilder private var wageSection: some View {
        if let wage, wage.status == "AWAITING_ACK" {
            Text("تأكيد استلام الأجر").font(.wathb(16, .medium))
            Text(wage.amountDisplay.arabicAmount).font(.wathb(22, .bold)).foregroundStyle(Brand.primary)
            let method = ArabicFormat.paymentMethod(wage.declarations?.first?.paymentMethod)
            if !method.isEmpty { Text(method).font(.wathb(14)).foregroundStyle(Brand.muted) }
            HStack(spacing: 8) {
                Button("تأكيد الاستلام") { gate.request(wage.id) }.buttonStyle(PrimaryButtonStyle())
                Button("اعتراض") { disputeReason = ""; disputing = true }.buttonStyle(OutlineButtonStyle(color: Brand.error))
            }
            .disabled(busy)
        } else if let wage, ["VERIFIED_PAID", "DECLARED"].contains(wage.status) {
            Text("✓ تم دفع أجرك").font(.wathb(16)).foregroundStyle(Brand.tertiary)
        } else if let wage {
            Text("الأجر: \(StatusLabels.label(StatusLabels.wageForWorker, wage.status))").font(.wathb(16)).foregroundStyle(Brand.muted)
        } else {
            Text("جاري تحميل بيانات الأجر...").font(.wathb(16)).foregroundStyle(Brand.muted)
        }
    }

    private func confirmOrDispute(confirm: @escaping () -> Void, dispute: @escaping () -> Void) -> some View {
        HStack(spacing: 8) {
            Button("أؤكد", action: confirm).buttonStyle(PrimaryButtonStyle())
            Button("أعترض", action: dispute).buttonStyle(OutlineButtonStyle(color: Brand.error))
        }
        .disabled(busy)
    }

    // MARK: Loading and actions

    private func load() async {
        if let fresh = try? await API.assignment(a.id) { assignment = fresh }
        async let records = try? API.attendance(a.id)
        async let done = try? API.completion(a.id)
        async let wages = try? API.wages()
        let (r, c, w) = await (records, done, wages)
        attendance = r ?? attendance ?? []
        if let c { completion = c }
        completionLoaded = true
        if let w { wage = w.first { $0.assignment == a.id } }
    }

    private func reloadAssignmentAndWage() async {
        if let fresh = try? await API.assignment(a.id) { assignment = fresh }
        if let w = try? await API.wages() { wage = w.first { $0.assignment == a.id } }
    }

    private func perform(_ success: String = "تم بنجاح", _ action: @escaping () async throws -> Void) {
        guard !busy else { return }
        busy = true
        Task {
            defer { busy = false }
            do {
                try await action()
                toast = success
                if let fresh = try? await API.assignment(a.id) { assignment = fresh }
            } catch {
                toast = error.localizedDescription
            }
        }
    }
}

extension String {
    /// "٧٫٥" or "7.5" → "7.5" for the hours field.
    var asciiDigitsKeepingDot: String {
        String(compactMap { c -> Character? in
            if let d = c.wholeNumberValue { return Character(String(d)) }
            return c == "." || c == "٫" ? "." : nil
        }.prefix(5))
    }
}
