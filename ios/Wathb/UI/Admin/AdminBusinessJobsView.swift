import SwiftUI

// MARK: - «المنشآت» → business details → its jobs, worked on behalf of the business

/// Shown inside the business details: add a job as a draft, and publish its drafts after confirming the terms.
struct AdminBusinessJobsSection: View {
    let business: AdminBusiness
    @State private var jobs: [Job]?
    @State private var error: String?
    @State private var message: String?

    private var drafts: [Job] { (jobs ?? []).filter { ["DRAFT", "PENDING_REVIEW"].contains($0.status) } }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Divider().padding(.vertical, 6)
            Text("وظائف المنشأة").font(.wathb(17, .bold))

            if business.verificationStatus != "APPROVED" {
                Text("تُضاف الوظائف وتُنشر للمنشآت الموافق عليها فقط.").font(.wathb(14)).foregroundStyle(Brand.muted)
            } else {
                NavigationLink {
                    AdminJobFormView(business: business) { message = "حُفظت الوظيفة مسودة وأُبلغت المنشأة" }
                } label: {
                    Label("إضافة وظيفة نيابة عن المنشأة", systemImage: "plus")
                }
                .buttonStyle(OutlineButtonStyle())

                if let message { Text(message).font(.wathb(14)).foregroundStyle(Brand.primary) }

                Text("المسودات").font(.wathb(15, .bold)).padding(.top, 6)
                if jobs != nil {
                    if drafts.isEmpty {
                        Text("لا توجد مسودات").font(.wathb(14)).foregroundStyle(Brand.muted)
                    }
                    ForEach(drafts) { draftRow($0) }
                } else if let error {
                    MessageView(message: error, isError: true) { Task { await load() } }
                } else {
                    LoadingView().frame(height: 80)
                }
            }
        }
        // Also reloads when coming back from the form or a publish.
        .onAppear { Task { await load() } }
    }

    private func draftRow(_ job: Job) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(job.title).font(.wathb(16, .medium))
            Text("\(ArabicFormat.date(job.workDate)) · \(ArabicFormat.time(job.startTime)) – \(ArabicFormat.time(job.endTime))")
                .font(.wathb(13)).foregroundStyle(Brand.muted)
            Text("\(ArabicFormat.wage(job.wageAmount, currency: job.wageCurrency, basis: job.wageBasis)) · \(job.numWorkersNeeded.arabic) عمال")
                .font(.wathb(13)).foregroundStyle(Brand.muted)
            NavigationLink {
                AdminPublishConfirmView(job: job, businessName: business.legalName) {
                    message = "نُشرت الوظيفة وأُبلغت المنشأة"
                }
            } label: {
                Text("نشر نيابة عن المنشأة")
            }
            .buttonStyle(PrimaryButtonStyle())
        }
        .card()
    }

    private func load() async {
        guard business.verificationStatus == "APPROVED" else { return }
        do { jobs = try await API.adminBusinessJobs(business.id); error = nil }
        catch { if jobs == nil { self.error = error.localizedDescription } }
    }
}

/// «إضافة وظيفة نيابة عن المنشأة»: the business's own form; the server validates it the same way and keeps it a draft.
struct AdminJobFormView: View {
    let business: AdminBusiness
    let onSaved: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        JobForm(buttonTitle: "حفظ كمسودة",
                footnote: "تُحفظ الوظيفة مسودة باسم المنشأة ويصل إشعار لصاحبها. لا تُنشر إلا بعد مراجعة الشروط وتأكيدها من قائمة المسودات.") { request in
            do {
                _ = try await API.adminCreateJob(business.id, request)
                onSaved()
                dismiss()
                return nil
            } catch let e as APIError where e.status == 403 {
                return "المنشأة غير موافق عليها أو موقوفة، أو ليس لديك صلاحية إدارية"
            } catch {
                return error.localizedDescription
            }
        }
        .navigationTitle(business.legalName)
        .navigationBarTitleDisplayMode(.inline)
    }
}

/// The full terms, confirmed before publishing. Only this exact version is published.
struct AdminPublishConfirmView: View {
    let job: Job
    let businessName: String
    let onPublished: () -> Void
    @State private var reason = ""
    @State private var busy = false
    @State private var error: String?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text("راجع الشروط قبل النشر").font(.wathb(15)).foregroundStyle(Brand.muted)
                Text(job.title).font(.wathb(20, .bold))
                DetailRow(label: "المنشأة", value: businessName)
                Divider()
                DetailRow(label: "تاريخ العمل", value: ArabicFormat.date(job.workDate))
                DetailRow(label: "الساعات", value: "\(ArabicFormat.time(job.startTime)) – \(ArabicFormat.time(job.endTime))")
                DetailRow(label: "الأجر", value: ArabicFormat.wage(job.wageAmount, currency: job.wageCurrency, basis: job.wageBasis))
                DetailRow(label: "عدد العمال", value: job.numWorkersNeeded.arabic)
                DetailRow(label: "المدينة", value: job.locationCity)
                DetailRow(label: "العنوان", value: job.locationAddress)
                DetailRow(label: "الدفع", value: "عبر Jawwal Pay يوم العمل نفسه")
                if job.isFunded { DetailRow(label: "التمويل", value: "ممولة من صندوق دعم العمال") }

                section("وصف الوظيفة", job.description)
                section("المهارات المطلوبة", job.requiredSkills)
                section("اشتراطات الحضور", job.attendanceRequirements)
                section("سياسة الإلغاء", job.cancellationPolicy)
                section("شروط إضافية", job.additionalConditions)

                Divider().padding(.vertical, 4)
                FormField(label: "سبب النشر نيابة عن المنشأة (اختياري)", text: $reason)
                Text("لا تكتب اسمًا أو رقم هاتف في الملاحظة").font(.wathb(12)).foregroundStyle(Brand.muted)
                Text("بعد النشر يرى العمال الوظيفة فورًا ويصل إشعار للمنشأة.").font(.wathb(13)).foregroundStyle(Brand.muted)
                if let error { Text(error).font(.wathb(14)).foregroundStyle(Brand.error) }
                LoadingButton(title: "تأكيد النشر", loading: busy) { publish() }.padding(.top, 8)
            }
            .padding(20)
        }
        .background(Brand.background)
        .navigationTitle("تأكيد النشر")
        .navigationBarTitleDisplayMode(.inline)
    }

    @ViewBuilder private func section(_ title: String, _ text: String?) -> some View {
        if let text, !text.isBlank {
            Divider()
            Text(title).font(.wathb(15, .bold))
            Text(text).font(.wathb(15))
        }
    }

    private func publish() {
        guard let version = job.version else { error = "تعذّر قراءة نسخة الوظيفة. ارجع وأعد فتحها."; return }
        busy = true
        Task {
            defer { busy = false }
            do {
                _ = try await API.adminPublishJob(job.id, version: version, reason: reason.trimmed)
                onPublished()
                dismiss()
            } catch let e as APIError where e.status == 409 {
                error = "تغيّرت شروط الوظيفة بعد فتح هذه الشاشة. ارجع وأعد فتحها لمراجعة الشروط الجديدة."
            } catch let e as APIError where e.status == 403 {
                error = "ليس لديك صلاحية إدارية"
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}
