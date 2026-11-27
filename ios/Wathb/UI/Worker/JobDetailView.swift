import SwiftUI
import MapKit

struct JobDetailView: View {
    let jobId: String

    enum ApplyState: Equatable { case idle, loading, applied, alreadyApplied }

    @State private var job: Job?
    @State private var error: String?
    @State private var coverNote = ""
    @State private var applyState = ApplyState.idle
    @State private var toast: String?
    @Environment(\.openURL) private var openURL

    var body: some View {
        ScrollView {
            if let job {
                content(job)
            } else if let error {
                MessageView(message: error, isError: true) { Task { await load() } }
            } else {
                LoadingView().frame(height: 400)
            }
        }
        .background(Brand.background)
        .refreshable { await load() }
        .safeAreaInset(edge: .bottom) {
            if job?.status == "PUBLISHED" { applyBar }
        }
        .navigationTitle("تفاصيل الوظيفة")
        .navigationBarTitleDisplayMode(.inline)
        .task { if job == nil { await load() } }
        .toast($toast)
    }

    private func content(_ job: Job) -> some View {
        let coordinate = CityCoordinates.of(job.locationCity)
        return VStack(alignment: .leading, spacing: 12) {
            Text(job.title).font(.wathb(22, .bold))
            Text(job.businessName).font(.wathb(15)).foregroundStyle(Brand.muted)
            Divider()
            Map(initialPosition: .region(MKCoordinateRegion(center: coordinate,
                                                            latitudinalMeters: 1500, longitudinalMeters: 1500))) {
                Marker(job.title, coordinate: coordinate).tint(Brand.deepTeal)
            }
            .frame(height: 200)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            Button("افتح في الخرائط") {
                let item = MKMapItem(placemark: MKPlacemark(coordinate: coordinate))
                item.name = job.title
                item.openInMaps()
            }
            .buttonStyle(OutlineButtonStyle())

            DetailRow(label: "الموقع", value: "\(job.locationCity) — \(job.locationAddress)")
            DetailRow(label: "تاريخ العمل", value: ArabicFormat.date(job.workDate))
            DetailRow(label: "الوقت", value: "\(ArabicFormat.time(job.startTime)) – \(ArabicFormat.time(job.endTime))")
            DetailRow(label: "عدد العمال المطلوبين", value: job.numWorkersNeeded.arabic)
            Divider()
            DetailRow(label: "الأجر", value: ArabicFormat.wage(job.wageAmount, currency: job.wageCurrency, basis: job.wageBasis))
            DetailRow(label: "الدفع", value: "يوميًا، فور انتهاء العمل")

            section("وصف الوظيفة", job.description)
            section("المهارات المطلوبة", job.requiredSkills)
            section("اشتراطات الحضور", job.attendanceRequirements)
            if job.isFunded {
                Divider()
                Text("هذه الوظيفة ممولة من خلال صندوق دعم العمال").font(.wathb(15)).foregroundStyle(Brand.secondary)
            }
        }
        .padding(16)
    }

    @ViewBuilder
    private func section(_ title: String, _ text: String) -> some View {
        if !text.isBlank {
            Divider()
            Text(title).font(.wathb(16, .bold))
            Text(text).font(.wathb(15))
        }
    }

    private var applyBar: some View {
        VStack(spacing: 8) {
            if applyState == .idle || applyState == .loading {
                TextField("ملاحظة لصاحب العمل (اختياري)", text: $coverNote)
                    .font(.wathb(15))
                    .fieldBox()
            }
            switch applyState {
            case .applied:
                Button("تم تقديم طلبك ✓") {}.buttonStyle(PrimaryButtonStyle()).disabled(true)
            case .alreadyApplied:
                Button("تقدّمت لهذه الوظيفة من قبل") {}.buttonStyle(PrimaryButtonStyle()).disabled(true)
            default:
                LoadingButton(title: "تقدّم للوظيفة", loading: applyState == .loading, action: apply)
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .background(.bar)
    }

    private func load() async {
        do { job = try await API.job(jobId); error = nil }
        catch { if job == nil { self.error = error.localizedDescription } }
    }

    private func apply() {
        applyState = .loading
        Task {
            do {
                _ = try await API.apply(jobId: jobId, coverNote: coverNote.trimmed)
                applyState = .applied
                toast = "تم تقديم طلبك بنجاح"
            } catch let e as APIError where e.status == 409 {
                applyState = .alreadyApplied
                toast = "لقد تقدّمت لهذه الوظيفة من قبل"
            } catch let e as APIError where e.status == 403 {
                applyState = .idle
                toast = "غير مصرح لك بالتقدم لهذه الوظيفة"
            } catch {
                applyState = .idle
                toast = error.localizedDescription
            }
        }
    }
}
