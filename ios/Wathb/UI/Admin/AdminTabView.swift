import SwiftUI

/// Admin home (android AdminMainScreen): «اللوحة»، «المنشآت»، «العمال»، «الاعتراضات».
struct AdminTabView: View {
    var body: some View {
        TabView {
            NavigationStack { AdminDashboardView() }
                .tabItem { Label("اللوحة", systemImage: "square.grid.2x2.fill") }
            NavigationStack { AdminBusinessesView() }
                .tabItem { Label("المنشآت", systemImage: "building.2.fill") }
            NavigationStack { AdminWorkersView() }
                .tabItem { Label("العمال", systemImage: "person.2.fill") }
            NavigationStack { AdminDisputesView() }
                .tabItem { Label("الاعتراضات", systemImage: "hammer.fill") }
        }
    }
}

/// Horizontal filter chips.
struct FilterChips<Value: Hashable>: View {
    let options: [(Value, String)]
    @Binding var selection: Value

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(options, id: \.0) { value, label in
                    let selected = value == selection
                    Button(label) { selection = value }
                        .font(.wathb(14, .medium))
                        .foregroundStyle(selected ? .white : .primary)
                        .padding(.horizontal, 14).padding(.vertical, 7)
                        .background(selected ? Brand.primary : Brand.card, in: Capsule())
                        .overlay(Capsule().stroke(selected ? .clear : Brand.border))
                }
            }
            .padding(.horizontal, 16).padding(.vertical, 8)
        }
    }
}

// MARK: - «اللوحة»

struct AdminDashboardView: View {
    @State private var summary: PilotSummary?
    @State private var error: String?
    @State private var deleting = false
    @State private var toast: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if let s = summary {
                    section("الحسابات الموثّقة", ("منشآت موثّقة", s.verifiedBusinesses), ("عمال موثّقون", s.verifiedWorkers))
                    section("الوظائف والتقديمات", ("وظائف منشورة", s.publishedJobs), ("تقديمات", s.applications))
                    section("المهام", ("مهام مقبولة", s.acceptedAssignments), ("أيام عمل مكتملة", s.completedWorkerDays))
                    section("الأجور", ("التزامات مُنشأة", s.wageObligationsCreated), ("مدفوعات مُعلنة", s.paymentsDeclared))
                    metrics(("مدفوعات موثّقة", s.paymentsVerifiedPaid), ("إجمالي موثّق (₪)", s.totalVerifiedPaidMinorUnits / 100))
                    section("النزاعات", ("نزاعات مفتوحة", s.disputesOpened), ("نزاعات محلولة", s.disputesResolved))
                } else if let error {
                    MessageView(message: error, isError: true) { Task { await load() } }
                } else {
                    LoadingView().frame(height: 400)
                }
                SupportWhatsappButton().padding(.top, 8)
                AccountSection(deleting: $deleting, toast: $toast).padding(.top, 8)
            }
            .padding(16)
        }
        .background(Brand.background)
        .refreshable { await load() }
        .task { await load() }
        .navigationTitle("لوحة التحكم")
        .navigationBarTitleDisplayMode(.inline)
        .toast($toast)
    }

    @ViewBuilder
    private func section(_ title: String, _ a: (String, Int), _ b: (String, Int)) -> some View {
        Text(title).font(.wathb(13, .bold)).foregroundStyle(Brand.primary).padding(.top, 4)
        metrics(a, b)
    }

    private func metrics(_ a: (String, Int), _ b: (String, Int)) -> some View {
        HStack(spacing: 12) { metric(a); metric(b) }
    }

    private func metric(_ m: (String, Int)) -> some View {
        VStack(spacing: 4) {
            Text(m.1.arabic).font(.wathb(24, .bold))
            Text(m.0).font(.wathb(12)).foregroundStyle(Brand.muted)
        }
        .frame(maxWidth: .infinity)
        .padding(16)
        .background(Brand.border.opacity(0.5), in: RoundedRectangle(cornerRadius: 12))
    }

    private func load() async {
        do { summary = try await API.pilotSummary(); error = nil }
        catch { if summary == nil { self.error = error.localizedDescription } }
    }
}

// MARK: - «المنشآت»

struct AdminBusinessesView: View {
    @State private var filter: String? = nil
    @State private var businesses: [AdminBusiness]?
    @State private var error: String?
    @State private var selected: AdminBusiness?
    @State private var toast: String?

    var body: some View {
        VStack(spacing: 0) {
            FilterChips(options: [(nil, "الكل"), ("PENDING", "معلق"), ("APPROVED", "موافق"),
                                  ("REJECTED", "مرفوض"), ("SUSPENDED", "موقوف")], selection: $filter)
            ScrollView {
                LazyVStack(spacing: 8) {
                    if let businesses {
                        if businesses.isEmpty { MessageView(message: "لا توجد نتائج") }
                        ForEach(businesses) { b in
                            Button { selected = b } label: { row(b) }.buttonStyle(.plain)
                        }
                    } else if let error {
                        MessageView(message: error, isError: true) { Task { await load() } }
                    } else {
                        LoadingView().frame(height: 300)
                    }
                }
                .padding(.horizontal, 16).padding(.bottom, 16)
            }
            .refreshable { await load() }
        }
        .background(Brand.background)
        .task(id: filter) { await load() }
        .navigationTitle("مراجعة المنشآت")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $selected) { b in
            BusinessVerifySheet(business: b) { message in
                toast = message
                Task { await load() }
            }
        }
        .toast($toast)
    }

    private func row(_ b: AdminBusiness) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .top) {
                Text(b.legalName).font(.wathb(16, .medium))
                Spacer()
                StatusBadge(text: AdminLabels.verification(b.verificationStatus), color: AdminLabels.color(b.verificationStatus))
            }
            if let email = b.email, !email.isEmpty { Text(email).font(.wathb(13)).foregroundStyle(Brand.muted) }
            if let city = b.locationCity, !city.isEmpty { Text(city).font(.wathb(13)).foregroundStyle(Brand.muted) }
        }
        .card()
    }

    private func load() async {
        do { businesses = try await API.adminBusinesses(status: filter); error = nil }
        catch { businesses = nil; self.error = error.localizedDescription }
    }
}

struct BusinessVerifySheet: View {
    let business: AdminBusiness
    let onDone: (String) -> Void
    @State private var action = "approve"
    @State private var reason = ""
    @State private var busy = false
    @State private var error: String?
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL

    private var needsReason: Bool { action != "approve" }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    Text("الحالة: \(AdminLabels.verification(business.verificationStatus))").font(.wathb(15))
                    detail("الاسم التجاري", business.tradeName)
                    detail("رقم التسجيل", business.registrationNumber)
                    detail("البريد الإلكتروني", business.email)
                    detail("المدينة", business.locationCity)
                    detail("العنوان", business.locationAddress)
                    detail("جهة الاتصال", business.contactName)
                    HStack {
                        DetailRow(label: "هاتف الاتصال", value: business.contactPhone.localPhone)
                        if let url = Contact.call(business.contactPhone) {
                            Button { openURL(url) } label: { Image(systemName: "phone.fill") }
                        }
                    }
                    detail("تاريخ التوثيق", business.verifiedAt.map { ArabicFormat.date($0) })
                    detail("سبب الإيقاف", business.suspensionReason)

                    Text("اختر الإجراء:").font(.wathb(15, .bold)).padding(.top, 8)
                    Picker("الإجراء", selection: $action) {
                        Text("موافقة").tag("approve")
                        Text("رفض").tag("reject")
                        Text("إيقاف").tag("suspend")
                    }
                    .pickerStyle(.segmented)
                    if needsReason {
                        FormField(label: "السبب (مطلوب)", text: $reason)
                        Text("لا تكتب اسمًا أو رقم هاتف في الملاحظة").font(.wathb(12)).foregroundStyle(Brand.muted)
                    }
                    if let error { Text(error).font(.wathb(14)).foregroundStyle(Brand.error) }
                    LoadingButton(title: "تأكيد", loading: busy, color: action == "approve" ? Brand.primary : Brand.error) { submit() }
                        .disabled(needsReason && reason.isBlank)
                        .padding(.top, 8)

                    AdminBusinessJobsSection(business: business)
                }
                .padding(20)
            }
            .navigationTitle(business.legalName)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("إلغاء") { dismiss() } } }
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    @ViewBuilder private func detail(_ label: String, _ value: String?) -> some View {
        if let value, !value.isBlank { DetailRow(label: label, value: value) }
    }

    private func submit() {
        busy = true
        Task {
            defer { busy = false }
            do {
                _ = try await API.verifyBusiness(business.id, action: action, reason: needsReason ? reason.trimmed : "")
                onDone("تم تحديث حالة المنشأة")
                dismiss()
            } catch let e as APIError where e.status == 403 {
                error = "ليس لديك صلاحية إدارية"
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}

enum AdminLabels {
    static func verification(_ s: String) -> String {
        ["PENDING": "معلق", "APPROVED": "موافق عليه", "REJECTED": "مرفوض", "SUSPENDED": "موقوف"][s] ?? StatusLabels.unmapped
    }

    static func color(_ s: String) -> Color {
        switch s {
        case "APPROVED": return Brand.primary
        case "REJECTED": return Brand.error
        case "SUSPENDED": return Brand.tertiary
        default: return Brand.secondary
        }
    }

    static func dispute(_ s: String) -> String {
        ["OPEN": "مفتوح", "IN_REVIEW": "قيد المراجعة", "RESOLVED": "محلول", "CLOSED": "مغلق"][s] ?? StatusLabels.unmapped
    }
}

// MARK: - «العمال»

struct AdminWorkersView: View {
    @State private var verified: Bool? = nil
    @State private var search = ""
    @State private var workers: [AdminWorker]?
    @State private var error: String?
    @State private var busy = false
    @State private var toast: String?
    @State private var suspendTarget: AdminWorker?

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                TextField("بحث (اسم / هاتف)", text: $search)
                    .font(.wathb(16)).submitLabel(.search)
                    .onSubmit { Task { await load() } }
                    .fieldBox()
                Button("بحث") { Task { await load() } }.buttonStyle(PrimaryButtonStyle()).frame(width: 80)
            }
            .padding(.horizontal, 16).padding(.top, 8)
            FilterChips(options: [(nil, "الكل"), (false, "غير موثّق"), (true, "موثّق")], selection: $verified)
            ScrollView {
                LazyVStack(spacing: 10) {
                    if let workers {
                        if workers.isEmpty { MessageView(message: "لا يوجد عمال مطابقون") }
                        ForEach(workers) { row($0) }
                    } else if let error {
                        MessageView(message: error, isError: true) { Task { await load() } }
                    } else {
                        LoadingView().frame(height: 300)
                    }
                }
                .padding(.horizontal, 16).padding(.bottom, 16)
            }
            .refreshable { await load() }
        }
        .background(Brand.background)
        .task(id: verified) { await load() }
        .navigationTitle("العمال")
        .navigationBarTitleDisplayMode(.inline)
        .toast($toast)
        .alert("إيقاف العامل", isPresented: Binding(get: { suspendTarget != nil }, set: { if !$0 { suspendTarget = nil } })) {
            Button("إيقاف", role: .destructive) { if let w = suspendTarget { act(w, "suspend") } }
            Button("إلغاء", role: .cancel) {}
        } message: {
            Text("هل تريد إيقاف \(suspendTarget?.fullName ?? "")؟")
        }
    }

    private func row(_ w: AdminWorker) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .top) {
                Text(w.fullName).font(.wathb(16, .medium))
                Spacer()
                StatusBadge(text: w.isVerified ? "موثّق" : "غير موثّق", color: w.isVerified ? Brand.primary : Brand.muted)
            }
            Text(w.phone.localPhone).font(.wathb(13)).foregroundStyle(Brand.muted)
            if let city = w.locationCity, !city.isEmpty { Text(city).font(.wathb(13)).foregroundStyle(Brand.muted) }
            if w.isVerified {
                Button("إيقاف") { suspendTarget = w }.buttonStyle(OutlineButtonStyle(color: Brand.error)).disabled(busy)
            } else {
                Button("توثيق") { act(w, "verify") }.buttonStyle(PrimaryButtonStyle()).disabled(busy)
            }
        }
        .card()
    }

    private func load() async {
        do { workers = try await API.adminWorkers(verified: verified, search: search); error = nil }
        catch { workers = nil; self.error = error.localizedDescription }
    }

    private func act(_ w: AdminWorker, _ action: String) {
        busy = true
        Task {
            defer { busy = false }
            do {
                _ = try await API.verifyWorker(w.id, action: action)
                toast = action == "verify" ? "تم توثيق العامل" : "تم إيقاف العامل"
                await load()
            } catch let e as APIError where e.status == 403 {
                toast = "ليس لديك صلاحية إدارية"
            } catch {
                toast = error.localizedDescription
            }
        }
    }
}
