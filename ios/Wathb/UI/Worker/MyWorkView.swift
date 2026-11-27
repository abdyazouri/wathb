import SwiftUI

/// «شغلي»: «طلباتي» (before the work starts), «مهامي» (from the start time on) and «أجوري».
@MainActor
@Observable
final class MyWorkModel {
    var applications: [JobApplication] = []
    var assignments: [Assignment] = []
    var wages: [WageObligation] = []
    var loading = true
    var error: String?
    var busy = false
    var toast: String?
    var now = Gaza.now()

    var split: MyWorkSplit { splitMyWork(applications: applications, assignments: assignments, now: now) }

    func wage(for assignment: Assignment) -> WageObligation? {
        wages.first { $0.id == assignment.wageObligationId || $0.assignment == assignment.id }
    }

    func load() async {
        now = Gaza.now()
        do {
            async let apps = API.myApplications()
            async let tasks = API.assignments()
            async let pay = API.wages()
            (applications, assignments, wages) = try await (apps, tasks, pay)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
        loading = false
    }

    /// Runs one action at a time, then reloads everything (an offer changes the application too).
    func perform(success: String = "تم بنجاح", _ action: @escaping () async throws -> Void) {
        guard !busy else { return }
        busy = true
        Task {
            defer { busy = false }
            do {
                try await action()
                toast = success
            } catch {
                toast = error.localizedDescription
            }
            await load()
        }
    }

    func accept(_ a: Assignment) { perform { _ = try await API.accept(a.id) } }
    func decline(_ a: Assignment) { perform { _ = try await API.decline(a.id) } }
    func requestWage(_ a: Assignment) { perform(success: "أُرسل طلب أجرك") { _ = try await API.requestWage(a.id) } }
    func withdraw(_ app: JobApplication) { perform { _ = try await API.withdraw(jobId: app.job, applicationId: app.id) } }

    func acknowledge(_ wageId: String, password: String?) {
        perform(success: "تم تأكيد الاستلام") { _ = try await API.acknowledge(wageId, password: password) }
    }

    func disputeWage(_ wageId: String, reason: String) {
        perform(success: "أُرسل اعتراضك") { _ = try await API.disputePayment(wageId, description: reason) }
    }
}

struct MyWorkView: View {
    @State private var model = MyWorkModel()
    @State private var tab = 0
    @State private var gate = AcknowledgeGate()

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $tab) {
                Text("طلباتي").tag(0)
                Text("مهامي").tag(1)
                Text("أجوري").tag(2)
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 16).padding(.vertical, 8)

            ScrollView {
                LazyVStack(spacing: 12) {
                    if model.loading {
                        LoadingView().frame(height: 400)
                    } else if let error = model.error {
                        MessageView(message: error, isError: true) { Task { await model.load() } }
                    } else {
                        switch tab {
                        case 0: applicationsList
                        case 1: tasksList
                        default: wagesList
                        }
                    }
                }
                .padding(16)
            }
            .refreshable { await model.load() }
        }
        .background(Brand.background)
        .navigationTitle("شغلي")
        .navigationBarTitleDisplayMode(.inline)
        // Fresh lists each time the worker comes back (e.g. from the task details).
        .onAppear { Task { await model.load() } }
        // A job moves from «طلباتي» to «مهامي» at its start time.
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(60))
                model.now = Gaza.now()
            }
        }
        .toast($model.toast)
        .acknowledgeGate(gate) { id, password in model.acknowledge(id, password: password) }
        .workerDestinations()
    }

    @ViewBuilder private var applicationsList: some View {
        let items = model.split.applications
        if items.isEmpty {
            MessageView(message: "لم تتقدم لأي وظيفة بعد")
        } else {
            ForEach(items) { item in
                switch item {
                case .offer(let a):
                    AssignmentCard(assignment: a, started: false, wage: nil, model: model, gate: gate)
                case .application(let app):
                    ApplicationCard(app: app, busy: model.busy) { model.withdraw(app) }
                }
            }
        }
    }

    @ViewBuilder private var tasksList: some View {
        let tasks = model.split.tasks
        if tasks.isEmpty {
            MessageView(message: "لا توجد مهام بدأت بعد.\nالمهمة المقبولة تنتقل إلى هنا عند بدء وقت العمل.")
        } else {
            ForEach(tasks) { a in
                AssignmentCard(assignment: a, started: true, wage: model.wage(for: a), model: model, gate: gate)
            }
        }
    }

    @ViewBuilder private var wagesList: some View {
        if model.wages.isEmpty {
            MessageView(message: "لا توجد التزامات أجور حالياً")
        } else {
            ForEach(model.wages) { w in WageCard(wage: w, model: model, gate: gate) }
        }
    }
}

// MARK: - «طلباتي»: a plain application

struct ApplicationCard: View {
    let app: JobApplication
    let busy: Bool
    let onWithdraw: () -> Void
    @State private var confirm = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                Text(app.jobTitle).font(.wathb(16, .medium))
                Spacer()
                Text(StatusLabels.label(StatusLabels.applicationForWorker, app.status))
                    .font(.wathb(12, .medium)).foregroundStyle(color)
            }
            Text("تاريخ التقديم: \(ArabicFormat.date(app.appliedAt))").font(.wathb(13, .light)).foregroundStyle(Brand.muted)
            if !app.coverNote.isBlank {
                Text(app.coverNote).font(.wathb(13)).foregroundStyle(Brand.muted)
            }
            if ["PENDING", "OFFERED"].contains(app.status) {
                Button("سحب الطلب") { confirm = true }
                    .buttonStyle(OutlineButtonStyle(color: Brand.error)).disabled(busy)
            }
        }
        .card()
        .alert("سحب الطلب", isPresented: $confirm) {
            Button("سحب", role: .destructive, action: onWithdraw)
            Button("إلغاء", role: .cancel) {}
        } message: {
            Text("هل تريد سحب طلبك لـ\"\(app.jobTitle)\"؟")
        }
    }

    private var color: Color {
        switch app.status {
        case "PENDING": return Brand.secondary
        case "OFFERED": return Brand.primary
        case "ACCEPTED": return Brand.tertiary
        case "REJECTED", "CANCELLED": return Brand.error
        default: return Brand.muted
        }
    }
}
