import SwiftUI

/// «أجوري»: one wage, with «تأكيد استلام الأجر» / «لم أستلم أجري» while it awaits the worker.
struct WageCard: View {
    let wage: WageObligation
    let model: MyWorkModel
    let gate: AcknowledgeGate

    @State private var confirm = false
    @State private var disputing = false
    @State private var disputeReason = ""

    /// The server lists declarations newest first.
    private var latest: PaymentDeclaration? { wage.declarations?.first }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                Text(wage.jobTitle).font(.wathb(17, .medium))
                Spacer()
                StatusBadge(text: StatusLabels.label(StatusLabels.wageForWorker, wage.status), color: statusColor)
            }
            Text(wage.amountDisplay.arabicAmount).font(.wathb(20, .bold)).foregroundStyle(Brand.primary)
            muted("تاريخ الاستحقاق: \(ArabicFormat.date(wage.dueDate))")
            if let latest {
                muted("طريقة الدفع: \(ArabicFormat.paymentMethod(latest.paymentMethod))")
                muted("تاريخ الدفع المُعلَن: \(ArabicFormat.date(latest.paymentDate))")
            }

            if wage.status == "AWAITING_ACK" {
                if latest?.providerConfirmed == true {
                    // Jawwal Pay itself confirmed the transfer: received unless disputed within 24 h.
                    Note(text: "وصلك أجرك عبر Jawwal Pay. إن لم يصلك اضغط «لم أستلم أجري» خلال ٢٤ ساعة، وبعدها يُعتبر مستلمًا.")
                } else if daysSinceDeclaration >= 3 {
                    Note(text: "تنبيه: مضى \(daysSinceDeclaration.arabic) أيام على إعلان الدفع. يرجى الإقرار أو الاعتراض فوراً.",
                         background: Brand.errorContainer)
                } else if daysSinceDeclaration >= 1 {
                    Note(text: "يرجى مراجعة إعلان الدفع وتأكيد استلامك أو الاعتراض عليه.", background: Brand.warningContainer)
                }
                Button("تأكيد استلام الأجر") { confirm = true }
                    .buttonStyle(PrimaryButtonStyle()).disabled(model.busy)
                Button("لم أستلم أجري") { disputeReason = ""; disputing = true }
                    .buttonStyle(OutlineButtonStyle(color: Brand.error)).disabled(model.busy)
            }
        }
        .card()
        .alert("تأكيد استلام الأجر", isPresented: $confirm) {
            Button("نعم، استلمت الأجر") { gate.request(wage.id) }
            Button("إلغاء", role: .cancel) {}
        } message: {
            Text("هل تؤكد استلام \(wage.amountDisplay.arabicAmount) من صاحب العمل؟\n\nلا يمكن التراجع عن هذا الإجراء.")
        }
        .wageDisputeAlert(isPresented: $disputing, reason: $disputeReason, amount: wage.amountDisplay) {
            model.disputeWage(wage.id, reason: disputeReason)
        }
    }

    private func muted(_ text: String) -> some View {
        Text(text).font(.wathb(13, .light)).foregroundStyle(Brand.muted)
    }

    private var daysSinceDeclaration: Int {
        guard let declared = latest?.declaredAt.prefix(10) else { return 0 }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = Gaza.timeZone
        f.dateFormat = "yyyy-MM-dd"
        guard let from = f.date(from: String(declared)), let to = f.date(from: Gaza.today()) else { return 0 }
        return Calendar(identifier: .gregorian).dateComponents([.day], from: from, to: to).day ?? 0
    }

    private var statusColor: Color {
        switch wage.status {
        case "PENDING", "UNDER_REVIEW": return Brand.secondary
        case "DUE", "REJECTED", "DISPUTED", "CANCELLED": return Brand.error
        case "AWAITING_ACK", "DECLARED": return Brand.primary
        case "VERIFIED_PAID": return Brand.tertiary
        default: return Brand.muted
        }
    }
}
