import Foundation

// Port of android viewmodels/MyWorkSplit.kt. Work dates and times are Gaza local time on the
// server (TIME_ZONE = "Asia/Gaza"); moments are compared as "yyyy-MM-ddTHH:mm" strings.

enum Gaza {
    static let timeZone = TimeZone(identifier: "Asia/Gaza")!

    private static func format(_ pattern: String, _ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = timeZone
        f.dateFormat = pattern
        return f.string(from: date)
    }

    /// "2026-11-27T09:30"
    static func now(_ date: Date = Date()) -> String { format("yyyy-MM-dd'T'HH:mm", date) }

    /// "2026-11-27"
    static func today(_ date: Date = Date()) -> String { format("yyyy-MM-dd", date) }
}

extension Assignment {
    /// Work date + start time, or nil if the server did not send them.
    var workStart: String? {
        guard let d = jobWorkDate, d.count >= 10, let t = jobStartTime, t.count >= 5 else { return nil }
        return "\(d.prefix(10))T\(t.prefix(5))"
    }

    func hasStarted(now: String) -> Bool { workStart.map { now >= $0 } ?? true }

    /// The work date has come (Gaza time).
    func workDayReached(today: String) -> Bool {
        guard let d = jobWorkDate, d.count >= 10 else { return false }
        return today >= String(d.prefix(10))
    }

    /// The server lets a worker cancel only before the work day.
    func canWorkerCancel(today: String) -> Bool {
        guard status == "ACCEPTED", let d = jobWorkDate, d.count >= 10 else { return false }
        return today < String(d.prefix(10))
    }

    /// «أتممت يوم عملي واطلب أجري»: on an accepted job, from the start of its work date (Gaza),
    /// until someone has recorded completion.
    func canRequestWage(today: String) -> Bool {
        status == "ACCEPTED" && completionStatus == nil && workDayReached(today: today)
    }

    /// A value from the agreed terms. The snapshot's keys may arrive snake_case or camelCase.
    func term(_ snakeKey: String) -> JSONValue? {
        guard let snap = termsSnapshot else { return nil }
        if let v = snap[snakeKey] { return v }
        let parts = snakeKey.split(separator: "_")
        let camel = parts.first.map(String.init)! + parts.dropFirst().map { $0.capitalized }.joined()
        return snap[camel]
    }
}

/// One row of «طلباتي»: an offer/accepted job (assignment) or a plain application.
enum MyApplicationsItem: Identifiable, Hashable {
    case offer(Assignment)
    case application(JobApplication)

    var id: String {
        switch self {
        case .offer(let a): return "offer-\(a.id)"
        case .application(let app): return "app-\(app.id)"
        }
    }
}

struct MyWorkSplit {
    /// From applying until the work starts.
    let applications: [MyApplicationsItem]
    /// From the start time on: attendance, finishing the job, the wage.
    let tasks: [Assignment]
}

/// «طلباتي» holds everything before the work starts: pending/closed applications, offers
/// (accept or decline) and accepted jobs whose start time has not come yet.
/// «مهامي» holds a job from its start time (work date + start time, Gaza time) onward.
func splitMyWork(applications: [JobApplication], assignments: [Assignment], now: String) -> MyWorkSplit {
    var tasks: [Assignment] = [], beforeWork: [Assignment] = []
    for a in assignments {
        let started: Bool
        switch a.status {
        case "OFFERED", "DECLINED": started = false
        case "ACTIVE", "COMPLETED": started = true
        default: started = a.hasStarted(now: now)  // ACCEPTED, CANCELLED
        }
        if started { tasks.append(a) } else { beforeWork.append(a) }
    }
    // An application that led to an offer is shown once, as the offer/assignment.
    let withAssignment = Set(assignments.map(\.id))
    let jobsWithAssignment = Set(assignments.map(\.job))
    let plain = applications.filter { app in
        if let aid = app.assignmentId { return !withAssignment.contains(aid) }
        return !jobsWithAssignment.contains(app.job)
    }

    let offerOrder = ["OFFERED": 0, "ACCEPTED": 1, "CANCELLED": 3, "DECLINED": 3]
    func rank(_ item: MyApplicationsItem) -> Int {
        switch item {
        case .offer(let a): return offerOrder[a.status] ?? 3
        case .application(let app): return app.status == "PENDING" ? 2 : 3
        }
    }
    func start(_ item: MyApplicationsItem) -> String {
        if case .offer(let a) = item, let s = a.workStart { return s }
        return "~"  // after every date: upcoming jobs soonest first
    }
    let items = (beforeWork.map { MyApplicationsItem.offer($0) } + plain.map { .application($0) })
        .enumerated()
        .sorted { l, r in
            let (a, b) = (l.element, r.element)
            if rank(a) != rank(b) { return rank(a) < rank(b) }
            if start(a) != start(b) { return start(a) < start(b) }
            return l.offset < r.offset
        }
        .map(\.element)

    let taskOrder = ["ACTIVE": 0, "ACCEPTED": 0, "COMPLETED": 1, "CANCELLED": 2]
    let sortedTasks = tasks.enumerated().sorted { l, r in
        let (a, b) = (l.element, r.element)
        let (ra, rb) = (taskOrder[a.status] ?? 2, taskOrder[b.status] ?? 2)
        if ra != rb { return ra < rb }
        let (sa, sb) = (a.workStart ?? "", b.workStart ?? "")
        if sa != sb { return sa > sb }  // latest first
        return l.offset < r.offset
    }.map(\.element)
    return MyWorkSplit(applications: items, tasks: sortedTasks)
}
