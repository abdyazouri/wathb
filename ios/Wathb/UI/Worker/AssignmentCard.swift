import SwiftUI

/// An offer or accepted job. `started`: its start time has come («مهامي»); otherwise it is in «طلباتي».
struct AssignmentCard: View {
    let assignment: Assignment
    let started: Bool
    let wage: WageObligation?
    let model: MyWorkModel
    let gate: AcknowledgeGate

    @State private var confirmRequest = false
    @State private var disputing = false
    @State private var disputeReason = ""

    private var a: Assignment { assignment }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                Text(a.jobTitle).font(.wathb(17, .medium))
                Spacer()
                StatusBadge(text: StatusLabels.label(StatusLabels.assignment, a.status), color: statusColor)
            }
            Text(a.businessName).font(.wathb(14)).foregroundStyle(Brand.muted)
            if let offered = a.offeredAt, !offered.isEmpty {
                small("تاريخ العرض: \(ArabicFormat.date(offered))")
            }
            if let accepted = a.acceptedAt, !accepted.isEmpty {
                small("تاريخ القبول: \(ArabicFormat.date(accepted))")
            }

            if a.status == "OFFERED" { offeredTerms }
            if a.termsSnapshot != nil, !["OFFERED", "DECLINED", "COMPLETED"].contains(a.status) { agreedTerms }

            actions
        }
        .card()
        .alert("أتممت يوم عملي واطلب أجري", isPresented: $confirmRequest) {
            Button("إرسال الطلب") { model.requestWage(a) }
            Button("إلغاء", role: .cancel) {}
        } message: {
            Text("سيصل طلب أجرك إلى صاحب العمل الآن. إن لم يرد خلال ٢٤ ساعة يتأكد إتمام العمل تلقائيًا ويصبح أجرك مستحقًا.")
        }
        .wageDisputeAlert(isPresented: $disputing, reason: $disputeReason, amount: wage?.amountDisplay) {
            if let wage { model.disputeWage(wage.id, reason: disputeReason) }
        }
    }

    // MARK: Terms

    @ViewBuilder private var offeredTerms: some View {
        if let d = a.jobWorkDate, !d.isEmpty { small("يوم العمل: \(ArabicFormat.date(d))", muted: false) }
        if let s = a.jobStartTime, let e = a.jobEndTime {
            small("الوقت: \(ArabicFormat.time(s)) — \(ArabicFormat.time(e))", muted: false)
        }
        if let city = a.jobLocationCity, !city.isEmpty {
            small("الموقع: \(city)\(address(a.jobLocationAddress))", muted: false)
        }
        if let amount = a.jobWageAmount, let currency = a.jobWageCurrency {
            Text("الأجر: \(ArabicFormat.wage(amount, currency: currency, basis: a.jobWageBasis ?? "")) (\(ArabicFormat.basisWord(a.jobWageBasis)))")
                .font(.wathb(15)).foregroundStyle(Brand.primary)
        }
    }

    @ViewBuilder private var agreedTerms: some View {
        Text("الشروط المتفق عليها").font(.wathb(13, .bold)).foregroundStyle(Brand.primary).padding(.top, 4)
        if let d = a.term("work_date")?.string { small("يوم العمل: \(ArabicFormat.date(d))", muted: false) }
        if let s = a.term("start_time")?.string, let e = a.term("end_time")?.string {
            small("الوقت: \(ArabicFormat.time(s)) — \(ArabicFormat.time(e))", muted: false)
        }
        if let city = a.term("location_city")?.string, !city.isEmpty {
            small("الموقع: \(city)\(address(a.term("location_address")?.string))", muted: false)
        }
        if let amount = a.term("wage_amount")?.int, let currency = a.term("wage_currency")?.string {
            let basis = a.term("wage_basis")?.string
            Text("الأجر: \(ArabicFormat.wage(amount, currency: currency, basis: basis ?? "")) (\(ArabicFormat.basisWord(basis)))")
                .font(.wathb(15)).foregroundStyle(Brand.primary)
        }
    }

    // MARK: Actions

    @ViewBuilder private var actions: some View {
        switch a.status {
        case "OFFERED":
            // Applying said "I'm interested"; this confirms "I'll come on these terms",
            // and the terms are fixed for the wage and any dispute.
            Text("اختارك صاحب العمل! راجع الشروط أعلاه وأكّد أنك ستحضر.")
                .font(.wathb(15, .bold)).foregroundStyle(Brand.primary).padding(.top, 4)
            if let changed = a.changedTerms, !changed.isEmpty {
                Note(text: "تغيّر منذ تقدّمت: \(TermLabels.changed(changed))", background: Brand.errorContainer)
            }
            HStack(spacing: 8) {
                Button("أؤكد حضوري") { model.accept(a) }.buttonStyle(PrimaryButtonStyle())
                Button("لا أستطيع") { model.decline(a) }.buttonStyle(OutlineButtonStyle(color: Brand.error))
            }
            .disabled(model.busy)

        case "COMPLETED":
            if let wage, wage.status == "AWAITING_ACK" {
                Text("أجرك: \(wage.amountDisplay.arabicAmount)").font(.wathb(16, .bold)).foregroundStyle(Brand.primary)
                HStack(spacing: 8) {
                    Button("تأكيد الاستلام") { gate.request(wage.id) }.buttonStyle(PrimaryButtonStyle())
                    Button("اعتراض") { disputeReason = ""; disputing = true }
                        .buttonStyle(OutlineButtonStyle(color: Brand.error))
                }
                .disabled(model.busy)
            } else if let wage {
                Text("الأجر: \(wage.amountDisplay.arabicAmount) — \(StatusLabels.label(StatusLabels.wageForWorker, wage.status))")
                    .font(.wathb(15)).foregroundStyle(wage.status == "VERIFIED_PAID" ? Brand.tertiary : Brand.muted)
            }
            NavigationLink("فتح المهمة", value: WorkerRoute.assignment(a)).buttonStyle(OutlineButtonStyle())

        case "ACCEPTED", "ACTIVE":
            WageRequestStatus(assignment: a)
            if a.canRequestWage(today: Gaza.today()) {
                Button("أتممت يوم عملي واطلب أجري") { confirmRequest = true }
                    .buttonStyle(PrimaryButtonStyle()).disabled(model.busy)
            }
            if started {
                NavigationLink("فتح المهمة", value: WorkerRoute.assignment(a)).buttonStyle(OutlineButtonStyle())
            } else {
                if let d = a.jobWorkDate, let t = a.jobStartTime {
                    Text("تبدأ \(ArabicFormat.date(d)) الساعة \(ArabicFormat.time(t))، وتنتقل إلى «مهامي» عند بدايتها.")
                        .font(.wathb(13)).foregroundStyle(Brand.tertiary)
                }
                NavigationLink("التفاصيل", value: WorkerRoute.assignment(a)).buttonStyle(OutlineButtonStyle())
            }

        case "CANCELLED":
            if let reason = a.cancellationReason, !reason.isBlank {
                Text("سبب الإلغاء: \(reason)").font(.wathb(13)).foregroundStyle(Brand.error)
            }

        default:
            EmptyView()  // DECLINED: no action
        }
    }

    // MARK: Helpers

    private func small(_ text: String, muted: Bool = true) -> some View {
        Text(text).font(.wathb(13)).foregroundStyle(muted ? Brand.muted : .primary)
    }

    private func address(_ address: String?) -> String {
        guard let address, !address.isEmpty else { return "" }
        return "، \(address)"
    }

    private var statusColor: Color {
        switch a.status {
        case "OFFERED": return Brand.primary
        case "ACCEPTED", "COMPLETED": return Brand.tertiary
        case "ACTIVE": return Brand.secondary
        case "DECLINED", "CANCELLED": return Brand.error
        default: return Brand.muted
        }
    }
}

/// Where the worker's wage request stands, shown on the task card.
struct WageRequestStatus: View {
    let assignment: Assignment

    var body: some View {
        let byWorker = assignment.completionRequestedByWorker == true
        switch assignment.completionStatus {
        case "SUBMITTED":
            if byWorker {
                Text("✓ أرسلت طلب أجرك. بانتظار صاحب العمل، ويتأكد تلقائيًا بعد ٢٤ ساعة.")
                    .font(.wathb(15)).foregroundStyle(Brand.tertiary)
            } else {
                Text("سجّل صاحب العمل إتمام العمل — أكّده أو اعترض من صفحة المهمة.")
                    .font(.wathb(15)).foregroundStyle(Brand.primary)
            }
        case "DISPUTED":
            Text(byWorker ? "قال صاحب العمل إن العمل لم يتم، والنزاع لدى مشرف وَثْب."
                          : "تم الاعتراض على إتمام العمل، والنزاع لدى مشرف وَثْب.")
                .font(.wathb(15)).foregroundStyle(Brand.error)
        default:
            EmptyView()
        }
    }
}

extension View {
    /// «لم أستلم أجري»: a required reason, sent to the admin as a dispute.
    func wageDisputeAlert(isPresented: Binding<Bool>, reason: Binding<String>, amount: String?,
                          onSend: @escaping () -> Void) -> some View {
        alert("الإبلاغ عن عدم استلام الأجر", isPresented: isPresented) {
            TextField("سبب الاعتراض", text: reason)
            Button("إرسال الاعتراض", role: .destructive) {
                if !reason.wrappedValue.isBlank { onSend() }
            }
            Button("إلغاء", role: .cancel) {}
        } message: {
            Text("يرجى وصف المشكلة المتعلقة بأجر \(amount?.arabicAmount ?? "هذه المهمة").")
        }
    }
}
