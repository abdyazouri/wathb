import SwiftUI

/// What a business can do with a task, shared by the «المهام» card and the task screen.
@MainActor
@Observable
final class BusinessTaskActions {
    var busy = false
    var toast: String?

    /// «تأكيد ودفع الأجر» / «تأكيد إتمام العمل»: the wage becomes due and «تحويل الأجر» opens.
    func complete(_ a: Assignment, nav: BusinessNav, reload: @escaping () async -> Void) {
        run(reload) {
            let done = try await API.businessComplete(a.id)
            if let wage = done.wageObligationId { nav.open(.payment(wage)) } else { self.toast = "تم تأكيد إتمام العمل" }
        }
    }

    func reportNotDone(_ a: Assignment, category: String, notes: String, reload: @escaping () async -> Void) {
        run(reload) {
            _ = try await API.reportNotDone(a.id, category: category, notes: notes)
            self.toast = "أُرسل البلاغ إلى مشرف وَثْب"
        }
    }

    func cancel(_ a: Assignment, reason: String, reload: @escaping () async -> Void) {
        run(reload) {
            _ = try await API.cancel(a.id, reason: reason)
            self.toast = "أُلغيت المهمة"
        }
    }

    private func run(_ reload: @escaping () async -> Void, _ action: @escaping () async throws -> Void) {
        guard !busy else { return }
        busy = true
        Task {
            defer { busy = false }
            do { try await action() } catch { toast = error.localizedDescription }
            await reload()
        }
    }
}

// MARK: - «المهام»

struct BusinessAssignmentsView: View {
    @Environment(BusinessNav.self) private var nav
    @State private var assignments: [Assignment]?
    @State private var error: String?
    @State private var actions = BusinessTaskActions()

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 10) {
                if let assignments {
                    if assignments.isEmpty { MessageView(message: "لا توجد مهام نشطة حالياً") }
                    ForEach(assignments) { a in
                        BusinessTaskCard(assignment: a, actions: actions) { await load() }
                    }
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
        .navigationTitle("المهام")
        .navigationBarTitleDisplayMode(.inline)
        .toast($actions.toast)
    }

    private func load() async {
        do { assignments = try await API.assignments(); error = nil }
        catch { if assignments == nil { self.error = error.localizedDescription } }
    }
}

struct BusinessTaskCard: View {
    let assignment: Assignment
    let actions: BusinessTaskActions
    let reload: () async -> Void
    @Environment(BusinessNav.self) private var nav
    @State private var notDone = false

    private var a: Assignment { assignment }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button { nav.open(.assignment(a)) } label: {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .top) {
                        Text(a.jobTitle).font(.wathb(17, .medium))
                        Spacer()
                        StatusBadge(text: StatusLabels.label(StatusLabels.assignment, a.status), color: businessTaskColor(a.status))
                    }
                    Text("العامل: \(a.workerPhone.localPhone)").font(.wathb(14)).foregroundStyle(Brand.muted)
                    if let d = a.jobWorkDate, !d.isEmpty {
                        Text("يوم العمل: \(ArabicFormat.date(d))").font(.wathb(13)).foregroundStyle(Brand.muted)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            BusinessTaskActionsView(assignment: a, actions: actions, notDone: $notDone, reload: reload)
        }
        .card()
        .notDoneSheet(isPresented: $notDone) { category, notes in
            actions.reportNotDone(a, category: category, notes: notes, reload: reload)
        }
    }
}

/// The completion step of a task, as the business sees it.
struct BusinessTaskActionsView: View {
    let assignment: Assignment
    let actions: BusinessTaskActions
    @Binding var notDone: Bool
    let reload: () async -> Void
    @Environment(BusinessNav.self) private var nav
    @State private var confirmComplete = false

    private var a: Assignment { assignment }

    var body: some View {
        let active = ["ACCEPTED", "ACTIVE"].contains(a.status)
        let workerAsked = a.completionStatus == "SUBMITTED" && a.completionRequestedByWorker == true
        Group {
            if active && workerAsked {
                // The worker pressed «أتممت يوم عملي واطلب أجري».
                Note(text: "أتمّ العامل يوم العمل ويطلب أجره. إن لم ترد خلال ٢٤ ساعة يتأكد الإتمام تلقائيًا.")
                HStack(spacing: 8) {
                    Button("تأكيد ودفع الأجر") { actions.complete(a, nav: nav, reload: reload) }.buttonStyle(PrimaryButtonStyle())
                    Button("لم يتم العمل") { notDone = true }.buttonStyle(OutlineButtonStyle(color: Brand.error))
                }
                .disabled(actions.busy)
            } else if active && a.completionStatus == "DISPUTED" {
                Text(a.completionRequestedByWorker == true ? "أبلغت أن العمل لم يتم — النزاع لدى مشرف وَثْب."
                                                            : "اعترض العامل على إتمام العمل — النزاع لدى مشرف وَثْب.")
                    .font(.wathb(15)).foregroundStyle(Brand.error)
            } else if active {
                // The worker has not asked (yet): the business can still record completion.
                LoadingButton(title: "تأكيد إتمام العمل", loading: actions.busy) { confirmComplete = true }
            } else if a.status == "COMPLETED" {
                // «تحويل الأجر» only while the wage is unpaid (older servers send no status).
                if let wage = a.wageObligationId, ["PENDING", "DUE", "REJECTED"].contains(a.wageStatus ?? "DUE") {
                    Button("تحويل الأجر") { nav.open(.payment(wage)) }.buttonStyle(PrimaryButtonStyle())
                } else if let status = a.wageStatus {
                    Text("الأجر: \(businessWageLabel(status))").font(.wathb(14)).foregroundStyle(businessWageColor(status))
                }
                Text("✓ تم تأكيد إتمام العمل").font(.wathb(13)).foregroundStyle(Brand.muted)
            }
        }
        .alert("تأكيد إتمام العمل", isPresented: $confirmComplete) {
            Button("تأكيد") { actions.complete(a, nav: nav, reload: reload) }
            Button("إلغاء", role: .cancel) {}
        } message: {
            Text("سيتم تأكيد إتمام العمل ويصبح الأجر مستحقًا اليوم، ثم تفتح شاشة «تحويل الأجر».")
        }
    }
}

func businessTaskColor(_ s: String) -> Color {
    switch s {
    case "OFFERED": return Brand.primary
    case "ACCEPTED", "COMPLETED": return Brand.tertiary
    case "ACTIVE": return Brand.secondary
    case "DECLINED", "CANCELLED": return Brand.error
    default: return Brand.muted
    }
}

// MARK: - «لم يتم العمل»

extension View {
    /// A required reason and optional notes; opens a dispute for the admin.
    func notDoneSheet(isPresented: Binding<Bool>, onSend: @escaping (String, String) -> Void) -> some View {
        sheet(isPresented: isPresented) { NotDoneSheet(onSend: onSend) }
    }
}

private struct NotDoneSheet: View {
    let onSend: (String, String) -> Void
    @State private var category: String?
    @State private var notes = ""
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 12) {
                Text("سيُفتح نزاع يتابعه مشرف وَثْب، ولن يُسجَّل أجر حتى يُحسم.").font(.wathb(15))
                Text("السبب (مطلوب)").font(.wathb(14, .bold))
                ForEach([("WORKER_NO_SHOW", "العامل لم يحضر"), ("WORK_INCOMPLETE", "العمل لم يكتمل")], id: \.0) { value, label in
                    Button { category = value } label: {
                        HStack {
                            Image(systemName: category == value ? "largecircle.fill.circle" : "circle")
                            Text(label).font(.wathb(16))
                            Spacer()
                        }
                        .foregroundStyle(category == value ? Brand.primary : .primary)
                    }
                }
                FormField(label: "ملاحظات (اختياري)", text: $notes)
                Text("لا تكتب اسمًا أو رقم هاتف في الملاحظة").font(.wathb(12)).foregroundStyle(Brand.muted)
                Button("إرسال") {
                    if let category { onSend(category, notes.trimmed); dismiss() }
                }
                .buttonStyle(PrimaryButtonStyle(color: Brand.error))
                .disabled(category == nil)
                Spacer()
            }
            .padding(20)
            .navigationTitle("لم يتم العمل")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("إلغاء") { dismiss() } } }
        }
        .environment(\.layoutDirection, .rightToLeft)
        .presentationDetents([.medium, .large])
    }
}

// MARK: - «إدارة المهمة»

struct BusinessAssignmentDetailView: View {
    @State private var assignment: Assignment
    @State private var actions = BusinessTaskActions()
    @State private var notDone = false
    @State private var cancelling = false
    @State private var cancelReason = ""
    @Environment(\.openURL) private var openURL

    init(initial: Assignment) { _assignment = State(initialValue: initial) }

    private var a: Assignment { assignment }

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("العامل").font(.wathb(13, .medium)).foregroundStyle(Brand.muted)
                    Text(a.workerPhone.localPhone).font(.wathb(17, .medium))
                    HStack(spacing: 8) {
                        Button { if let u = Contact.call(a.workerPhone) { openURL(u) } } label: { Label("اتصال", systemImage: "phone") }
                            .buttonStyle(OutlineButtonStyle())
                        Button { if let u = Contact.whatsapp(a.workerPhone) { openURL(u) } } label: { Label("واتساب", systemImage: "message") }
                            .buttonStyle(OutlineButtonStyle())
                    }
                }
                .card()

                VStack(alignment: .leading, spacing: 12) {
                    Text("حالة المهمة").font(.wathb(13, .medium)).foregroundStyle(Brand.muted)
                    Text(a.jobTitle).font(.wathb(17, .bold))
                    if let d = a.jobWorkDate, let s = a.jobStartTime, let e = a.jobEndTime {
                        Text("\(ArabicFormat.date(d)) · \(ArabicFormat.time(s)) – \(ArabicFormat.time(e))")
                            .font(.wathb(14)).foregroundStyle(Brand.muted)
                    }
                    switch a.status {
                    case "OFFERED": Text("بانتظار قبول العامل").font(.wathb(16))
                    case "CANCELLED": Text("ملغاة").font(.wathb(16)).foregroundStyle(Brand.error)
                    case "DECLINED": Text("رفض العامل المهمة").font(.wathb(16)).foregroundStyle(Brand.muted)
                    default: EmptyView()
                    }
                    BusinessTaskActionsView(assignment: a, actions: actions, notDone: $notDone, reload: reload)
                }
                .card()

                if ["OFFERED", "ACCEPTED"].contains(a.status) {
                    Button("إلغاء المهمة") { cancelReason = ""; cancelling = true }
                        .buttonStyle(OutlineButtonStyle(color: Brand.error)).disabled(actions.busy)
                }
            }
            .padding(16)
        }
        .background(Brand.background)
        .refreshable { await reload() }
        .task { await reload() }
        .navigationTitle("إدارة المهمة")
        .navigationBarTitleDisplayMode(.inline)
        .toast($actions.toast)
        .notDoneSheet(isPresented: $notDone) { category, notes in
            actions.reportNotDone(a, category: category, notes: notes, reload: reload)
        }
        .alert("إلغاء المهمة", isPresented: $cancelling) {
            TextField("سبب الإلغاء (مطلوب)", text: $cancelReason)
            Button("تأكيد الإلغاء", role: .destructive) {
                guard !cancelReason.isBlank else { actions.toast = "اكتب سبب الإلغاء"; return }
                actions.cancel(a, reason: cancelReason.trimmed, reload: reload)
            }
            Button("تراجع", role: .cancel) {}
        } message: {
            Text("هل أنت متأكد أنك تريد إلغاء مهمة هذا العامل؟")
        }
    }

    private func reload() async {
        if let fresh = try? await API.assignment(a.id) { assignment = fresh }
    }
}
