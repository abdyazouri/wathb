import Foundation

/// An Arabic message ready for the screen. `status` is the HTTP code (nil: no answer).
struct APIError: Error, LocalizedError {
    let message: String
    var status: Int? = nil
    /// The raw error body, for screens that read extra keys (e.g. «تحويل الأجر»).
    var body: Data? = nil
    var errorDescription: String? { message }

    /// A key of the JSON error body (`failure`, `retry_after`, `needs_wallet`, …).
    func field(_ key: String) -> Any? {
        guard let body, let json = try? JSONSerialization.jsonObject(with: body) as? [String: Any] else { return nil }
        return json[key].flatMap { $0 is NSNull ? nil : $0 }
    }

    static let noConnection = APIError(message: "تعذّر الاتصال بالخادم. تحقّق من الإنترنت ثم حاول مرة أخرى.")
}

/// Talks to the Wathb API (same server and contract as the Android app).
/// Adds the access token, refreshes it once on a 401, and signs out only when
/// the server itself refused the refresh token.
actor APIClient {
    static let shared = APIClient()

    static let baseURL: URL = {
        let s = Bundle.main.object(forInfoDictionaryKey: "ApiBaseUrl") as? String
        return URL(string: s ?? "https://wathb-api2.onrender.com/api/v1/")!
    }()

    private let session: URLSession = {
        let c = URLSessionConfiguration.default
        c.timeoutIntervalForRequest = 30
        c.waitsForConnectivity = false
        return URLSession(configuration: c)
    }()
    private let decoder: JSONDecoder = {
        let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d
    }()
    private let encoder: JSONEncoder = {
        let e = JSONEncoder(); e.keyEncodingStrategy = .convertToSnakeCase; return e
    }()
    private var refreshTask: Task<Bool, Error>?

    // MARK: Requests

    func get<T: Decodable>(_ path: String, query: [String: String] = [:]) async throws -> T {
        try await send("GET", path, query: query, body: NoBody?.none)
    }

    func post<T: Decodable, B: Encodable>(_ path: String, _ body: B) async throws -> T {
        try await send("POST", path, body: body)
    }

    func post<T: Decodable>(_ path: String) async throws -> T {
        try await send("POST", path, body: NoBody?.none)
    }

    func patch<T: Decodable, B: Encodable>(_ path: String, _ body: B) async throws -> T {
        try await send("PATCH", path, body: body)
    }

    func patch<T: Decodable>(_ path: String) async throws -> T {
        try await send("PATCH", path, body: NoBody?.none)
    }

    /// For calls whose answer is not needed (204 or ignored body).
    func postIgnoringResult<B: Encodable>(_ path: String, _ body: B, authorized: Bool = true) async throws {
        _ = try await raw("POST", path, query: [:], body: try encoder.encode(body), authorized: authorized)
    }

    private func send<T: Decodable, B: Encodable>(_ method: String, _ path: String,
                                                 query: [String: String] = [:], body: B?) async throws -> T {
        let data = try await raw(method, path, query: query, body: try body.map { try encoder.encode($0) })
        let payload = data.isEmpty ? Data("{}".utf8) : data
        do { return try decoder.decode(T.self, from: payload) }
        catch { throw APIError(message: "ردّ غير متوقع من الخادم.") }
    }

    private func raw(_ method: String, _ path: String, query: [String: String], body: Data?,
                     authorized: Bool = true, retried: Bool = false) async throws -> Data {
        var components = URLComponents(url: Self.baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var request = URLRequest(url: components.url!)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("ar", forHTTPHeaderField: "Accept-Language")
        if let body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let token = authorized ? TokenStore.accessToken : nil
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }

        let data: Data, response: URLResponse
        do { (data, response) = try await session.data(for: request) }
        catch let e as URLError where e.code == .timedOut {
            throw APIError(message: "انتهت مهلة الاتصال بالخادم")
        } catch { throw APIError.noConnection }

        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        if code == 401, token != nil, !retried {
            if try await refreshTokens() {
                return try await raw(method, path, query: query, body: body, authorized: authorized, retried: true)
            }
            throw APIError(message: "انتهت الجلسة، سجّل الدخول من جديد.", status: 401)
        }
        guard (200..<300).contains(code) else {
            throw APIError(message: Self.message(from: data), status: code, body: data)
        }
        return data
    }

    // MARK: Token refresh

    /// One refresh at a time. True: new tokens saved. False: the server refused the
    /// refresh token, so the session is over. Throws when there was no verdict (offline, 5xx).
    private func refreshTokens() async throws -> Bool {
        if let refreshTask { return try await refreshTask.value }
        let task = Task<Bool, Error> {
            guard let refresh = TokenStore.refreshToken else { await Session.expire(); return false }
            var request = URLRequest(url: Self.baseURL.appendingPathComponent("auth/token/refresh/"))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try encoder.encode(RefreshRequest(refresh: refresh))
            let data: Data, response: URLResponse
            do { (data, response) = try await session.data(for: request) }
            catch { throw APIError.noConnection }
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            if (200..<300).contains(code), let r = try? decoder.decode(RefreshResponse.self, from: data) {
                TokenStore.save(access: r.access, refresh: r.refresh ?? refresh)
                return true
            }
            // Only 400/401 mean the server judged the refresh token and refused it.
            if code == 400 || code == 401 { await Session.expire(); return false }
            throw APIError.noConnection
        }
        refreshTask = task
        defer { refreshTask = nil }
        return try await task.value
    }

    // MARK: Error body → Arabic message

    /// The server sends {"error", "detail", "fields"?}. For a validation error the detail is only
    /// the generic «بعض الحقول غير صالحة.», so the per-field reasons in "fields" win.
    static func message(from data: Data) -> String {
        guard !data.isEmpty, let json = try? JSONSerialization.jsonObject(with: data) else { return "فشل الطلب" }
        guard let dict = json as? [String: Any] else { return messages(json).first ?? "خطأ في الطلب" }
        if let fields = dict["fields"] {
            var seen = Set<String>(), lines: [String] = []
            for m in messages(fields) where seen.insert(m).inserted { lines.append(m) }
            if !lines.isEmpty { return lines.joined(separator: "\n") }
        }
        if let detail = dict["detail"] as? String { return detail }
        if let nfe = dict["non_field_errors"] { return messages(nfe).first ?? "بيانات غير صالحة" }
        return messages(dict).first ?? "خطأ في الطلب"
    }

    /// First message of each field, in order; nested objects are flattened.
    private static func messages(_ value: Any) -> [String] {
        switch value {
        case let s as String: return [s]
        case let a as [Any]: return a.first.map { messages($0) } ?? []
        case let d as [String: Any]: return d.keys.sorted().flatMap { messages(d[$0]!) }
        default: return []
        }
    }
}
