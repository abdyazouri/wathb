import Foundation

/// The endpoints the iPhone app uses (paths as in android/data/api/*Api.kt).
enum API {
    fileprivate static var c: APIClient { .shared }

    // MARK: Auth

    static func login(phone: String, password: String) async throws -> User {
        let tokens: TokenPair = try await c.post("auth/login/", LoginRequest(phone: phone, password: password))
        TokenStore.save(access: tokens.access, refresh: tokens.refresh)
        do {
            let user: User = try await c.get("auth/me/")
            TokenStore.role = user.role
            return user
        } catch {
            TokenStore.clear()
            throw APIError(message: "تعذّر تحميل ملف المستخدم")
        }
    }

    static func registerWorker(_ r: RegisterWorkerRequest) async throws -> User {
        let resp: RegisterResponse = try await c.post("auth/register/", r)
        TokenStore.save(access: resp.access, refresh: resp.refresh)
        TokenStore.role = resp.user.role
        return resp.user
    }

    static func registerBusiness(_ r: RegisterBusinessRequest) async throws -> User {
        let resp: RegisterResponse = try await c.post("auth/register/", r)
        TokenStore.save(access: resp.access, refresh: resp.refresh)
        TokenStore.role = resp.user.role
        return resp.user
    }

    /// Blacklists the refresh token on the server (best effort), then wipes the session.
    static func logout() async {
        if let refresh = TokenStore.refreshToken {
            try? await c.postIgnoringResult("auth/logout/", RefreshRequest(refresh: refresh))
        }
        TokenStore.clear()
    }

    static func deleteAccount(password: String) async throws {
        try await c.postIgnoringResult("auth/delete-account/", PasswordRequest(password: password))
        TokenStore.clear()
    }

    static func config() async throws -> AppConfig {
        try await c.get("app/config/")
    }

    // MARK: Jobs

    static func jobs(page: Int) async throws -> Page<Job> {
        try await c.get("jobs/", query: ["page": String(page)])
    }

    static func job(_ id: String) async throws -> Job { try await c.get("jobs/\(id)/") }

    static func apply(jobId: String, coverNote: String) async throws -> JobApplication {
        try await c.post("jobs/\(jobId)/apply/", ApplyRequest(coverNote: coverNote))
    }

    static func withdraw(jobId: String, applicationId: String) async throws -> JobApplication {
        try await c.patch("jobs/\(jobId)/applications/\(applicationId)/", ApplicationActionRequest(action: "withdraw"))
    }

    // MARK: Worker

    static func myApplications() async throws -> [JobApplication] {
        let page: Page<JobApplication> = try await c.get("workers/applications/")
        return page.results
    }

    static func workerProfile() async throws -> WorkerProfile { try await c.get("workers/profile/") }

    static func updateWorkerProfile(_ u: WorkerProfileUpdate) async throws -> WorkerProfile {
        try await c.patch("workers/profile/", u)
    }

    // MARK: Assignments

    static func assignments() async throws -> [Assignment] {
        let page: Page<Assignment> = try await c.get("assignments/")
        return page.results
    }

    static func assignment(_ id: String) async throws -> Assignment { try await c.get("assignments/\(id)/") }
    static func accept(_ id: String) async throws -> Assignment { try await c.post("assignments/\(id)/accept/") }
    static func decline(_ id: String) async throws -> Assignment { try await c.post("assignments/\(id)/decline/") }

    static func cancel(_ id: String, reason: String) async throws -> Assignment {
        try await c.post("assignments/\(id)/cancel/", CancelRequest(reason: reason))
    }

    static func attendance(_ id: String) async throws -> [Attendance] { try await c.get("assignments/\(id)/attendance/") }

    static func checkIn(_ id: String, workDate: String) async throws -> Attendance {
        try await c.post("assignments/\(id)/attendance/", AttendanceSubmit(workDate: workDate, notes: ""))
    }

    static func confirmAttendance(_ id: String, record: String) async throws -> Attendance {
        try await c.patch("assignments/\(id)/attendance/\(record)/confirm/")
    }

    static func disputeAttendance(_ id: String, record: String) async throws -> Attendance {
        try await c.patch("assignments/\(id)/attendance/\(record)/dispute/")
    }

    /// Nil when nobody recorded completion yet (the server answers 404).
    static func completion(_ id: String) async throws -> Completion? {
        do { return try await c.get("assignments/\(id)/completion/") as Completion }
        catch let e as APIError where e.status == 404 { return nil }
    }

    /// «أتممت يوم عملي واطلب أجري». The server ignores a second press.
    static func requestWage(_ id: String, hoursWorked: String? = nil, notes: String = "") async throws -> Completion {
        try await c.post("assignments/\(id)/completion/", CompletionSubmit(hoursWorked: hoursWorked, notes: notes))
    }

    static func confirmCompletion(_ id: String) async throws -> Completion {
        try await c.patch("assignments/\(id)/completion/confirm/")
    }

    static func disputeCompletion(_ id: String) async throws -> Completion {
        try await c.patch("assignments/\(id)/completion/dispute/", [String: String]())
    }

    // MARK: Wages

    static func wages() async throws -> [WageObligation] {
        let page: Page<WageObligation> = try await c.get("wages/")
        return page.results
    }

    /// Call only after Face ID / passcode passed, or with the account password.
    static func acknowledge(_ wageId: String, password: String?) async throws -> WageObligation {
        try await c.post("wages/\(wageId)/acknowledge/", AcknowledgeRequest(password: password))
    }

    static func disputePayment(_ wageId: String, description: String) async throws -> WageObligation {
        try await c.post("wages/\(wageId)/dispute-payment/", DisputePaymentRequest(description: description))
    }

    // MARK: Notifications

    static func notifications() async throws -> [AppNotification] {
        let page: Page<AppNotification> = try await c.get("notifications/")
        return page.results
    }

    static func markRead(_ id: String) async throws -> AppNotification { try await c.patch("notifications/\(id)/read/") }
    static func markAllRead() async throws { try await c.postIgnoringResult("notifications/read-all/", NoBody()) }
}

// MARK: - Admin

extension API {

    static func pilotSummary() async throws -> PilotSummary { try await c.get("admin/reports/pilot-summary/") }

    static func adminBusinesses(status: String?) async throws -> [AdminBusiness] {
        let page: Page<AdminBusiness> = try await c.get("admin/businesses/",
                                                       query: status.map { ["verification_status": $0] } ?? [:])
        return page.results
    }

    static func verifyBusiness(_ id: Int, action: String, reason: String) async throws -> AdminBusiness {
        try await c.patch("admin/businesses/\(id)/verify/", AdminVerifyRequest(action: action, reason: reason))
    }

    static func adminWorkers(verified: Bool?, search: String) async throws -> [AdminWorker] {
        var query: [String: String] = [:]
        if let verified { query["is_verified"] = verified ? "true" : "false" }
        if !search.isBlank { query["search"] = search.trimmed }
        let page: Page<AdminWorker> = try await c.get("admin/workers/", query: query)
        return page.results
    }

    /// action: verify / suspend
    static func verifyWorker(_ id: Int, action: String) async throws -> AdminWorker {
        try await c.patch("admin/workers/\(id)/verify/", ["action": action])
    }

    static func wageDisputes() async throws -> [Dispute] {
        let page: Page<Dispute> = try await c.get("disputes/", query: ["category": "WAGE_DISPUTED"])
        return page.results
    }

    static func resolveDispute(_ id: String, notes: String) async throws -> Dispute {
        try await c.post("admin/disputes/\(id)/resolve/", ResolutionNotes(resolutionNotes: notes))
    }

    /// «الدفع تم» (verify) / «الدفع لم يتم» (reject); the server also resolves the dispute.
    static func settleWage(_ dispute: Dispute, action: String, notes: String) async throws {
        guard let wage = dispute.wageObligation, let declaration = dispute.disputedDeclaration else { return }
        try await c.postIgnoringResult("wages/\(wage)/declarations/\(declaration)/verify/",
                                       VerifyDeclarationRequest(action: action, reviewNotes: notes))
    }

    /// Wages awaiting the worker's acknowledgement for days: the admin calls the worker.
    static func staleWages() async throws -> [WageObligation] { try await c.get("admin/disputes/stale-wages/") }

    /// Wages due 3+ days with no payment declared: the admin calls the business.
    static func unpaidWages() async throws -> [WageObligation] { try await c.get("admin/disputes/unpaid-wages/") }

    /// action: confirmed_by_phone / disputed_by_phone
    static func phoneResolveWage(_ id: String, action: String, notes: String) async throws -> WageObligation {
        try await c.patch("wages/\(id)/admin-phone-resolve/", PhoneResolveRequest(action: action, notes: notes))
    }
}
