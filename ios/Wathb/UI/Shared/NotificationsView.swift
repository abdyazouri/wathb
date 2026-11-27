import SwiftUI

struct NotificationsView: View {
    @State private var items: [AppNotification]?
    @State private var error: String?
    @State private var openJob: String?
    @State private var openApplicants: Job?

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 8) {
                if let items {
                    if items.isEmpty {
                        MessageView(message: "لا توجد إشعارات")
                    }
                    ForEach(items) { n in
                        Button { open(n) } label: { row(n) }.buttonStyle(.plain)
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
        .task { await load() }
        .navigationTitle("الإشعارات")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if items?.contains(where: { !$0.isRead }) == true {
                ToolbarItem(placement: .topBarLeading) {
                    Button("قراءة الكل") {
                        Task { try? await API.markAllRead(); await load() }
                    }
                    .font(.wathb(15))
                }
            }
        }
        .navigationDestination(item: $openJob) { JobDetailView(jobId: $0) }
        .navigationDestination(item: $openApplicants) { ApplicantsView(job: $0) }
    }

    private func row(_ n: AppNotification) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .top) {
                Text(n.title).font(.wathb(15, n.isRead ? .regular : .bold))
                Spacer()
                Text(ArabicFormat.date(n.createdAt)).font(.wathb(11)).foregroundStyle(Brand.muted)
            }
            if !n.body.isBlank {
                Text(n.body).font(.wathb(13)).foregroundStyle(Brand.muted).multilineTextAlignment(.leading)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(n.isRead ? Brand.border.opacity(0.4) : Brand.tertiary.opacity(0.15), in: RoundedRectangle(cornerRadius: 12))
    }

    private func load() async {
        do { items = try await API.notifications(); error = nil }
        catch { if items == nil { self.error = error.localizedDescription } }
    }

    private func open(_ n: AppNotification) {
        if !n.isRead {
            Task { _ = try? await API.markRead(n.id); await load() }
        }
        guard n.relatedModel == "JobListing", let id = n.relatedId, !id.isEmpty else { return }
        if TokenStore.role == "BUSINESS" {
            // A business opens the job's applicants (the job page is the worker's view).
            Task { if let job = try? await API.job(id) { openApplicants = job } }
        } else {
            openJob = id
        }
    }
}

/// A role this version does not know (the session is kept; the account can sign out here).
struct OtherRoleView: View {
    let role: String
    @State private var deleting = false
    @State private var toast: String?

    var body: some View {
        VStack(spacing: 20) {
            Spacer()
            Text("وَثْب").font(.wathb(44, .black)).foregroundStyle(Brand.primary)
            Text("هذا الحساب غير مدعوم في هذه النسخة. حدّث التطبيق أو تواصل مع الدعم.")
                .font(.wathb(17)).multilineTextAlignment(.center)
            Spacer()
            AccountSection(deleting: $deleting, toast: $toast)
        }
        .padding(24)
        .background(Brand.background)
        .toast($toast)
    }
}
