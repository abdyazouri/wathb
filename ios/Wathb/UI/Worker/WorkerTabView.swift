import SwiftUI

/// Worker home: «الرئيسية» (jobs), «شغلي» (طلباتي / مهامي / أجوري), «حسابي».
struct WorkerTabView: View {
    @State private var tab = 0

    var body: some View {
        TabView(selection: $tab) {
            NavigationStack { JobsView() }
                .tabItem { Label("الرئيسية", systemImage: "house.fill") }.tag(0)
            NavigationStack { MyWorkView() }
                .tabItem { Label("شغلي", systemImage: "briefcase.fill") }.tag(1)
            NavigationStack { WorkerProfileView() }
                .tabItem { Label("حسابي", systemImage: "person.fill") }.tag(2)
        }
    }
}

/// Routes pushed inside the worker tabs.
enum WorkerRoute: Hashable {
    case job(String)
    case assignment(Assignment)
    case notifications
}

extension View {
    func workerDestinations() -> some View {
        navigationDestination(for: WorkerRoute.self) { route in
            switch route {
            case .job(let id): JobDetailView(jobId: id)
            case .assignment(let a): AssignmentDetailView(initial: a)
            case .notifications: NotificationsView()
            }
        }
    }
}

// MARK: - Jobs

@MainActor
@Observable
final class JobsModel {
    var jobs: [Job] = []
    var loading = true
    var error: String?
    var hasMore = false
    var loadingMore = false
    var unread = 0
    private var page = 1

    func load() async {
        page = 1
        do {
            let result = try await API.jobs(page: 1)
            jobs = result.results
            hasMore = result.next != nil
            error = nil
        } catch {
            if jobs.isEmpty { self.error = error.localizedDescription }
        }
        loading = false
        if let list = try? await API.notifications() { unread = list.filter { !$0.isRead }.count }
    }

    func loadMore() async {
        guard hasMore, !loadingMore else { return }
        loadingMore = true
        defer { loadingMore = false }
        if let result = try? await API.jobs(page: page + 1) {
            page += 1
            jobs += result.results.filter { j in !jobs.contains { $0.id == j.id } }
            hasMore = result.next != nil
        }
    }
}

struct JobsView: View {
    @State private var model = JobsModel()

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                if model.loading {
                    LoadingView().frame(height: 400)
                } else if let error = model.error {
                    MessageView(message: error, isError: true) { Task { await model.load() } }
                } else if model.jobs.isEmpty {
                    MessageView(message: "لا توجد وظائف متاحة حالياً")
                } else {
                    ForEach(model.jobs) { job in
                        NavigationLink(value: WorkerRoute.job(job.id)) { JobCard(job: job) }
                            .buttonStyle(.plain)
                            .onAppear { if job.id == model.jobs.last?.id { Task { await model.loadMore() } } }
                    }
                    if model.loadingMore { ProgressView().padding() }
                    SupportWhatsappButton().padding(.top, 4)
                }
            }
            .padding(16)
        }
        .background(Brand.background)
        .refreshable { await model.load() }
        .task { if model.loading { await model.load() } }
        .navigationTitle("وَثْب")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                NavigationLink(value: WorkerRoute.notifications) {
                    Image(systemName: model.unread > 0 ? "bell.badge.fill" : "bell")
                        .symbolRenderingMode(.multicolor)
                        .accessibilityLabel("الإشعارات")
                }
            }
        }
        .workerDestinations()
    }
}

struct JobCard: View {
    let job: Job

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(job.title).font(.wathb(17, .medium)).lineLimit(2)
                    Text(job.businessName).font(.wathb(13, .light)).foregroundStyle(Brand.muted)
                }
                Spacer()
                if job.isNew == true {
                    Text("جديد").font(.wathb(12, .medium)).foregroundStyle(.black)
                        .padding(.horizontal, 8).padding(.vertical, 3)
                        .background(Brand.gold, in: RoundedRectangle(cornerRadius: 4))
                }
            }
            Text(ArabicFormat.wage(job.wageAmount, currency: job.wageCurrency, basis: job.wageBasis))
                .font(.wathb(22, .bold)).foregroundStyle(Brand.primary)
            HStack {
                Label(job.locationCity, systemImage: "mappin.and.ellipse")
                Spacer()
                Text(ArabicFormat.date(job.workDate))
            }
            .font(.wathb(14)).foregroundStyle(Brand.muted)
            if let track = job.businessTrackRecord?.label, !track.isEmpty {
                Text(track).font(.wathb(12, .medium)).foregroundStyle(Brand.muted)
            }
            if job.isFunded {
                Text("ممول").font(.wathb(13)).foregroundStyle(Brand.secondary)
            }
        }
        .card()
    }
}
