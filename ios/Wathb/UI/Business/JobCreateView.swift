import SwiftUI

/// «نشر وظيفة جديدة». Payment is always Jawwal Pay, set by the server — nothing to choose.
struct JobCreateView: View {
    @Environment(BusinessNav.self) private var nav
    @State private var title = ""
    @State private var description = ""
    @State private var city = ""
    @State private var address = ""
    @State private var workDate = Calendar.current.date(byAdding: .day, value: 1, to: Date()) ?? Date()
    @State private var start = JobCreateView.time(hour: 8)
    @State private var end = JobCreateView.time(hour: 16)
    @State private var workers = "1"
    @State private var wage = ""
    @State private var basis = "PER_DAY"
    @State private var busy = false
    @State private var toast: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                FormField(label: "عنوان الوظيفة", text: $title)
                VStack(alignment: .leading, spacing: 6) {
                    Text("وصف الوظيفة").font(.wathb(14, .medium)).foregroundStyle(Brand.muted)
                    TextField("", text: $description, axis: .vertical)
                        .font(.wathb(17)).lineLimit(2...5)
                        .padding(.vertical, 12).fieldBox()
                }
                FormField(label: "المدينة", text: $city, contentType: .addressCity)
                FormField(label: "العنوان التفصيلي", text: $address, contentType: .streetAddressLine1)

                VStack(spacing: 10) {
                    DatePicker("تاريخ العمل", selection: $workDate, in: Calendar.current.startOfDay(for: Date())...,
                               displayedComponents: .date)
                    DatePicker("وقت البداية", selection: $start, displayedComponents: .hourAndMinute)
                    DatePicker("وقت النهاية", selection: $end, displayedComponents: .hourAndMinute)
                }
                .font(.wathb(16))
                .environment(\.locale, Locale(identifier: "ar"))
                .padding(14)
                .background(Brand.field, in: RoundedRectangle(cornerRadius: 12))
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(Brand.border))

                FormField(label: "عدد العمال المطلوبين", text: $workers, keyboard: .numberPad)
                FormField(label: "الأجر (بالشيكل الكامل)", text: $wage, keyboard: .numberPad)

                Text("أساس الأجر").font(.wathb(14, .medium)).foregroundStyle(Brand.muted)
                Picker("أساس الأجر", selection: $basis) {
                    Text("يومي").tag("PER_DAY")
                    Text("بالساعة").tag("PER_HOUR")
                    Text("بالمهمة").tag("PER_TASK")
                }
                .pickerStyle(.segmented)

                Text("يُدفع الأجر عبر Jawwal Pay يوم العمل نفسه.").font(.wathb(13)).foregroundStyle(Brand.muted)

                LoadingButton(title: "نشر الوظيفة", loading: busy, action: submit).padding(.top, 8)
            }
            .padding(16)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Brand.background)
        .navigationTitle("نشر وظيفة جديدة")
        .navigationBarTitleDisplayMode(.inline)
        .toast($toast)
    }

    private static func time(hour: Int) -> Date {
        Calendar.current.date(bySettingHour: hour, minute: 0, second: 0, of: Date()) ?? Date()
    }

    /// The date and times as the user picked them on the wall clock (Gaza is the server's zone).
    private func format(_ date: Date, _ pattern: String) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = .current
        f.dateFormat = pattern
        return f.string(from: date)
    }

    private func submit() {
        let shekels = Int(wage.asciiDigits) ?? 0
        let count = Int(workers.asciiDigits) ?? 0
        guard !title.isBlank, !city.isBlank, !address.isBlank else { toast = "يرجى ملء العنوان والمدينة والعنوان التفصيلي"; return }
        guard shekels > 0 else { toast = "اكتب الأجر بالشيكل"; return }
        guard count > 0 else { toast = "اكتب عدد العمال"; return }
        let request = JobCreateRequest(
            title: title.trimmed, description: description.trimmed,
            locationAddress: address.trimmed, locationCity: city.trimmed,
            workDate: format(workDate, "yyyy-MM-dd"), startTime: format(start, "HH:mm"), endTime: format(end, "HH:mm"),
            numWorkersNeeded: count, wageAmount: shekels * 100, wageBasis: basis)
        busy = true
        Task {
            defer { busy = false }
            let draft: Job
            do { draft = try await APIClient.shared.post("jobs/", request) }
            catch let e as APIError where e.status == 403 {
                toast = "حسابك لم يتم التحقق منه بعد. يرجى انتظار موافقة الإدارة."; return
            } catch { toast = error.localizedDescription; return }
            do {
                _ = try await API.publish(draft.id)
                nav.back()
            } catch {
                // The draft is saved; it can be published later from «وظائفي».
                toast = "حُفظت الوظيفة كمسودة ولم تُنشر: \(error.localizedDescription)"
                try? await Task.sleep(for: .seconds(2))
                nav.back()
            }
        }
    }
}
