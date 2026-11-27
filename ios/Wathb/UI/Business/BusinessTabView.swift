import SwiftUI

/// Business home (android BusinessMainScreen): «وظائفي»، «المهام»، «الأجور»، «حسابي».
struct BusinessTabView: View {
    @State private var tab = 0
    @State private var jobs = BusinessNav()
    @State private var tasks = BusinessNav()
    @State private var wages = BusinessNav()

    var body: some View {
        TabView(selection: $tab) {
            BusinessStack(nav: jobs) { BusinessJobsView() }
                .tabItem { Label("وظائفي", systemImage: "briefcase.fill") }.tag(0)
            BusinessStack(nav: tasks) { BusinessAssignmentsView() }
                .tabItem { Label("المهام", systemImage: "person.2.fill") }.tag(1)
            BusinessStack(nav: wages) { BusinessWagesView() }
                .tabItem { Label("الأجور", systemImage: "banknote.fill") }.tag(2)
            NavigationStack { BusinessProfileView() }
                .tabItem { Label("حسابي", systemImage: "person.crop.circle.fill") }.tag(3)
        }
    }
}

enum BusinessRoute: Hashable {
    case createJob
    case applicants(Job)
    case assignment(Assignment)
    /// «تحويل الأجر»
    case payment(String)
    case profile
    case notifications
}

/// The path of one tab, so a screen can open another (e.g. «تحويل الأجر» right after confirming the work).
@MainActor
@Observable
final class BusinessNav {
    var path: [BusinessRoute] = []
    func open(_ route: BusinessRoute) { path.append(route) }
    func back() { if !path.isEmpty { path.removeLast() } }
}

private struct BusinessStack<Root: View>: View {
    @Bindable var nav: BusinessNav
    @ViewBuilder let root: () -> Root

    var body: some View {
        NavigationStack(path: $nav.path) {
            root().navigationDestination(for: BusinessRoute.self) { route in
                switch route {
                case .createJob: JobCreateView()
                case .applicants(let job): ApplicantsView(job: job)
                case .assignment(let a): BusinessAssignmentDetailView(initial: a)
                case .payment(let id): WagePaymentView(wageId: id)
                case .profile: BusinessProfileView()
                case .notifications: NotificationsView()
                }
            }
        }
        .environment(nav)
    }
}

// MARK: - «وظائفي»

struct BusinessJobsView: View {
    @Environment(BusinessNav.self) private var nav
    @State private var jobs: [Job] = []
    @State private var loading = true
    @State private var error: String?
    @State private var unverified = false
    @State private var hasMore = false
    @State private var page = 1
    @State private var busyJob: String?
    @State private var toast: String?
    @State private var cancelling: Job?
    @State private var cancelReason = ""
    @State private var unread = 0

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                if loading {
                    LoadingView().frame(height: 400)
                } else if unverified {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("حسابك في انتظار التحقق").font(.wathb(22, .bold)).foregroundStyle(Brand.primary)
                        Text("يتم التحقق من الحسابات التجارية من قِبَل فريق وَثْب قبل السماح بنشر الوظائف. سنُخطرك عند الموافقة.")
                            .font(.wathb(16)).foregroundStyle(Brand.muted)
                    }
                    .padding(.vertical, 40)
                } else if let error {
                    MessageView(message: error, isError: true) { Task { await load() } }
                } else if jobs.isEmpty {
                    MessageView(message: "لا توجد وظائف منشورة بعد.\nاضغط + لنشر وظيفتك الأولى.")
                } else {
                    ForEach(jobs) { job in
                        jobCard(job)
                            .onAppear { if job.id == jobs.last?.id { Task { await loadMore() } } }
                    }
                    SupportWhatsappButton()
                }
            }
            .padding(16)
        }
        .background(Brand.background)
        .refreshable { await load() }  // e.g. after the admin approved the business
        .task { await load() }
        .navigationTitle("وَثْب")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button { nav.open(.notifications) } label: {
                    Image(systemName: unread > 0 ? "bell.badge.fill" : "bell").symbolRenderingMode(.multicolor)
                }
                .accessibilityLabel("الإشعارات")
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button { nav.open(.createJob) } label: { Image(systemName: "plus.circle.fill").font(.title3) }
                    .accessibilityLabel("نشر وظيفة")
            }
        }
        .toast($toast)
        .alert("إلغاء الوظيفة", isPresented: Binding(get: { cancelling != nil }, set: { if !$0 { cancelling = nil } })) {
            TextField("سبب الإلغاء (مطلوب)", text: $cancelReason)
            Button("تأكيد الإلغاء", role: .destructive) {
                guard let job = cancelling, !cancelReason.isBlank else { toast = "اكتب سبب الإلغاء"; return }
                act(job, success: "تم إلغاء الوظيفة") { _ = try await API.cancelJob(job.id, reason: cancelReason.trimmed) }
            }
            Button("تراجع", role: .cancel) {}
        } message: {
            Text("سيتم إلغاء جميع الطلبات والمهام المرتبطة بهذه الوظيفة.")
        }
    }

    private func jobCard(_ job: Job) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Button { nav.open(.applicants(job)) } label: {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .top) {
                        Text(job.title).font(.wathb(17, .medium)).lineLimit(1)
                        Spacer()
                        StatusBadge(text: StatusLabels.label(StatusLabels.job, job.status), color: jobColor(job.status))
                    }
                    Text("\(job.locationCity) · \(ArabicFormat.date(job.workDate))").font(.wathb(14)).foregroundStyle(Brand.muted)
                    Text(ArabicFormat.wage(job.wageAmount, currency: job.wageCurrency, basis: job.wageBasis))
                        .font(.wathb(15, .medium)).foregroundStyle(Brand.primary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            switch job.status {
            case "DRAFT":
                LoadingButton(title: "نشر الوظيفة", loading: busyJob == job.id) {
                    act(job, success: "نُشرت الوظيفة") { _ = try await API.publish(job.id) }
                }
            case "PUBLISHED":
                Button("إلغاء الوظيفة") { cancelReason = ""; cancelling = job }
                    .buttonStyle(OutlineButtonStyle(color: Brand.error))
            case "FILLED", "CANCELLED":
                LoadingButton(title: "انشر مرة ثانية", loading: busyJob == job.id) {
                    act(job, success: "تم إنشاء مسودة جديدة — اضغط «نشر الوظيفة» عليها") { _ = try await API.cloneJob(job.id) }
                }
            default:
                EmptyView()
            }
        }
        .card()
    }

    private func jobColor(_ s: String) -> Color {
        switch s {
        case "PUBLISHED": return Brand.primary
        case "PENDING_REVIEW": return Brand.secondary
        case "FILLED", "IN_PROGRESS": return Brand.tertiary
        case "CANCELLED": return Brand.error
        default: return Brand.muted
        }
    }

    private func load() async {
        do {
            let result = try await API.myJobs(page: 1)
            jobs = result.results; hasMore = result.next != nil; page = 1
            error = nil; unverified = false
        } catch let e as APIError where e.status == 403 {
            unverified = true
        } catch {
            if jobs.isEmpty { self.error = error.localizedDescription }
        }
        loading = false
        if let list = try? await API.notifications() { unread = list.filter { !$0.isRead }.count }
    }

    private func loadMore() async {
        guard hasMore, let result = try? await API.myJobs(page: page + 1) else { return }
        page += 1
        jobs += result.results.filter { j in !jobs.contains { $0.id == j.id } }
        hasMore = result.next != nil
    }

    private func act(_ job: Job, success: String, _ action: @escaping () async throws -> Void) {
        guard busyJob == nil else { return }
        busyJob = job.id
        Task {
            defer { busyJob = nil }
            do { try await action(); toast = success; await load() }
            catch { toast = error.localizedDescription }
        }
    }
}
