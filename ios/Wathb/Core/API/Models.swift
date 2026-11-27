import Foundation

// Server JSON is snake_case; APIClient decodes with .convertFromSnakeCase, so
// `wage_obligation_id` arrives as `wageObligationId`. Shapes match android ApiModels.kt.

// MARK: - Auth

struct LoginRequest: Encodable { let phone: String; let password: String }
struct TokenPair: Decodable { let access: String; let refresh: String }
struct RefreshRequest: Encodable { let refresh: String }
struct RefreshResponse: Decodable { let access: String; let refresh: String? }
struct PasswordRequest: Encodable { let password: String }

struct RegisterWorkerRequest: Encodable {
    let phone: String
    let password: String
    let role = "WORKER"
    let fullName: String
    let consentVersion: Int
}

struct RegisterBusinessRequest: Encodable {
    let phone: String
    let password: String
    let role = "BUSINESS"
    let legalName: String
    let contactName: String
    let contactPhone: String
    let consentVersion: Int
}

struct RegisterResponse: Decodable { let user: User; let access: String; let refresh: String }

struct User: Decodable {
    let id: String
    let phone: String
    let role: String
    let isVerified: Bool
}

// MARK: - Jobs

struct TrackRecord: Decodable, Hashable { let label: String }

struct Job: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let description: String
    let businessName: String
    let businessTrackRecord: TrackRecord?
    let locationCity: String
    let locationAddress: String
    let workDate: String
    let startTime: String
    let endTime: String
    let numWorkersNeeded: Int
    let requiredSkills: String
    let wageAmount: Int
    let wageCurrency: String
    let wageBasis: String
    let attendanceRequirements: String
    let isNew: Bool?
    let status: String
    let isFunded: Bool
}

struct Page<T: Decodable>: Decodable {
    let count: Int
    let next: String?
    let results: [T]
}

struct ApplyRequest: Encodable { let coverNote: String }
struct ApplicationActionRequest: Encodable { let action: String }

struct JobApplication: Decodable, Identifiable, Hashable {
    let id: String
    let job: String
    let jobTitle: String
    let status: String
    let coverNote: String
    let appliedAt: String
    let assignmentId: String?
    let assignmentStatus: String?
}

// MARK: - Worker profile

struct WorkerProfile: Decodable {
    let phone: String
    let isVerified: Bool
    let fullName: String
    let locationCity: String
    let locationRegion: String
    let isAvailable: Bool
}

struct WorkerProfileUpdate: Encodable {
    let fullName: String
    let locationCity: String
    let locationRegion: String
    let isAvailable: Bool
}

// MARK: - Assignments

struct Assignment: Decodable, Identifiable, Hashable {
    let id: String
    let job: String
    let jobTitle: String
    let workerPhone: String
    let businessName: String
    /// E.164, ready for tel: and wa.me links.
    let businessPhone: String?
    let jobWorkDate: String?
    let jobStartTime: String?
    let jobEndTime: String?
    let jobLocationCity: String?
    let jobLocationAddress: String?
    let jobWageAmount: Int?
    let jobWageCurrency: String?
    let jobWageBasis: String?
    let status: String
    /// Set by the server on accept; the terms the wage and any dispute rely on.
    let termsSnapshot: [String: JSONValue]?
    let offeredAt: String?
    let acceptedAt: String?
    let wageObligationId: String?
    /// On an offer: terms the business changed since the worker applied.
    let changedTerms: [String]?
    /// SUBMITTED / CONFIRMED / DISPUTED, or nil before anyone recorded completion.
    let completionStatus: String?
    /// True when the worker pressed «أتممت يوم عملي واطلب أجري».
    let completionRequestedByWorker: Bool?
}

struct Attendance: Decodable, Identifiable, Hashable {
    let id: String
    let submittedByPhone: String
    let workDate: String
    let status: String
}

struct AttendanceSubmit: Encodable { let workDate: String; let notes: String }

struct Completion: Decodable, Hashable {
    let id: String
    let submittedByPhone: String
    let status: String
}

struct CompletionSubmit: Encodable {
    let hoursWorked: String?
    let notes: String
}

struct CancelRequest: Encodable { let reason: String }

// MARK: - Wages

struct WageObligation: Decodable, Identifiable, Hashable {
    let id: String
    let assignment: String
    let jobTitle: String
    let amount: Int
    let currency: String
    let amountDisplay: String
    let dueDate: String
    let status: String
    /// Newest first.
    let declarations: [PaymentDeclaration]?
}

struct PaymentDeclaration: Decodable, Hashable {
    let id: String
    let paymentDate: String
    let paymentMethod: String
    let declaredAt: String
    /// True when Jawwal Pay itself confirmed the transfer (automatic mode).
    let providerConfirmed: Bool?
}

/// Body of POST wages/{id}/acknowledge/. `password` only when the phone has no Face ID,
/// Touch ID or passcode; nil is left out of the JSON (device check passed).
struct AcknowledgeRequest: Encodable { let password: String? }

struct DisputePaymentRequest: Encodable {
    let category = "PAYMENT_NOT_RECEIVED"
    let description: String
}

// MARK: - Notifications

struct AppNotification: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let body: String
    let relatedModel: String?
    let relatedId: String?
    let isRead: Bool
    let createdAt: String
}

// MARK: - App config

struct AppConfig: Decodable { let supportWhatsapp: String? }

struct Empty: Decodable {}

// MARK: - Loose JSON (terms_snapshot)

enum JSONValue: Decodable, Hashable {
    case string(String), number(Double), bool(Bool), null
    case array([JSONValue]), object([String: JSONValue])

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    var string: String? { if case .string(let s) = self { return s } else { return nil } }
    var int: Int? { if case .number(let n) = self { return Int(n) } else { return nil } }
}

/// The body of a request that sends none.
struct NoBody: Encodable {}
