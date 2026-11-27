import SwiftUI

/// «طلبات التوظيف» for one job: offer or reject, withdraw an offer, open the accepted task.
struct ApplicantsView: View {
    let job: Job
    @Environment(BusinessNav.self) private var nav
    @State private var applicants: [JobApplication]?
    @State private var error: String?
    @State private var busy = false
    @State private var toast: String?

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(job.title).font(.wathb(18, .bold))
                    Text("\(job.locationCity) · \(ArabicFormat.date(job.workDate)) · \(ArabicFormat.time(job.startTime))")
                        .font(.wathb(14)).foregroundStyle(Brand.muted)
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                if let applicants {
                    if applicants.isEmpty { MessageView(message: "لا توجد طلبات لهذه الوظيفة بعد") }
                    ForEach(applicants) { card($0) }
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
        .navigationTitle("طلبات التوظيف")
        .navigationBarTitleDisplayMode(.inline)
        .toast($toast)
    }

    private func card(_ app: JobApplication) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 6) {
                        if let name = app.workerName, !name.isEmpty { Text(name).font(.wathb(16, .medium)) }
                        let verified = app.workerIsVerified == true
                        Text(verified ? "موثّق" : "غير موثّق")
                            .font(.wathb(11, .medium))
                            .foregroundStyle(verified ? .white : Brand.muted)
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(verified ? Color(hex: 0x2E7D32) : Brand.border, in: RoundedRectangle(cornerRadius: 6))
                    }
                    if let phone = app.workerPhone, !phone.isEmpty {
                        Text(phone.localPhone).font(.wathb(13)).foregroundStyle(Brand.muted)
                    }
                }
                Spacer()
                Text(label(app.status)).font(.wathb(12, .medium)).foregroundStyle(color(app.status))
            }
            if !app.coverNote.isBlank { Text(app.coverNote).font(.wathb(14)).foregroundStyle(Brand.muted) }
            Text("تاريخ التقديم: \(ArabicFormat.date(app.appliedAt))").font(.wathb(12)).foregroundStyle(Brand.muted)

            switch app.status {
            case "PENDING":
                HStack(spacing: 8) {
                    Button("عرض الوظيفة") { act(app, "offer", success: "أُرسل العرض للعامل") }.buttonStyle(PrimaryButtonStyle())
                    Button("رفض") { act(app, "reject", success: "تم رفض الطلب") }.buttonStyle(OutlineButtonStyle(color: Brand.error))
                }
                .disabled(busy)
            case "OFFERED":
                Button("سحب العرض") { act(app, "reject", success: "سُحب العرض") }
                    .buttonStyle(OutlineButtonStyle(color: Brand.error)).disabled(busy)
            case "ACCEPTED":
                if let id = app.assignmentId {
                    Button("إدارة المهمة والحضور") { Task { await openTask(id) } }.buttonStyle(PrimaryButtonStyle())
                }
            default:
                EmptyView()
            }
        }
        .card()
    }

    private func label(_ s: String) -> String {
        ["PENDING": "معلق", "OFFERED": "عُرض عليه", "ACCEPTED": "قبل", "REJECTED": "مرفوض",
         "WITHDRAWN": "انسحب", "EXPIRED": "انتهت المهلة", "CANCELLED": "ملغى"][s] ?? StatusLabels.unmapped
    }

    private func color(_ s: String) -> Color {
        switch s {
        case "PENDING": return Brand.secondary
        case "OFFERED": return Brand.primary
        case "ACCEPTED": return Brand.tertiary
        case "REJECTED", "CANCELLED": return Brand.error
        default: return Brand.muted
        }
    }

    private func load() async {
        do { applicants = try await API.applicants(jobId: job.id); error = nil }
        catch { if applicants == nil { self.error = error.localizedDescription } }
    }

    private func act(_ app: JobApplication, _ action: String, success: String) {
        busy = true
        Task {
            defer { busy = false }
            do {
                _ = try await API.applicationAction(jobId: job.id, applicationId: app.id, action: action)
                toast = success
                await load()
            } catch {
                toast = error.localizedDescription
            }
        }
    }

    private func openTask(_ id: String) async {
        do { nav.open(.assignment(try await API.assignment(id))) }
        catch { toast = error.localizedDescription }
    }
}
