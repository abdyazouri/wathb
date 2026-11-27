import Foundation

/// Arabic label for every status value the server sends (copied from android StatusLabels.kt,
/// which a JVM test keeps in sync with the backend TextChoices). Unknown values read «غير محدد».
enum StatusLabels {
    static let unmapped = "غير محدد"

    static let job = [
        "DRAFT": "مسودة", "PENDING_REVIEW": "قيد المراجعة", "PUBLISHED": "منشور", "FILLED": "اكتمل العدد",
        "IN_PROGRESS": "قيد التنفيذ", "COMPLETED": "منتهية", "CANCELLED": "ملغاة",
    ]

    static let applicationForWorker = [
        "PENDING": "معلّق", "OFFERED": "معروض", "ACCEPTED": "مقبول", "REJECTED": "مرفوض",
        "WITHDRAWN": "مسحوب", "EXPIRED": "انتهت المهلة", "CANCELLED": "ملغى",
    ]

    static let assignment = [
        "OFFERED": "عرض جديد", "ACCEPTED": "مقبول", "DECLINED": "مرفوض", "ACTIVE": "نشط",
        "COMPLETED": "مكتمل", "CANCELLED": "ملغى",
    ]

    static let wageForWorker = [
        "PENDING": "معلق", "DUE": "مستحق", "DECLARED": "أُعلن الدفع", "AWAITING_ACK": "بانتظار تأكيدك",
        "UNDER_REVIEW": "قيد المراجعة", "DISPUTED": "متنازع عليه", "VERIFIED_PAID": "مدفوع ومؤكد",
        "REJECTED": "مرفوض", "CANCELLED": "ملغى",
    ]

    static let attendance = [
        "SUBMITTED": "بانتظار التأكيد", "CONFIRMED": "مؤكَّد", "DISPUTED": "معترَض عليه", "CANCELLED": "ملغى",
    ]

    static let completion = ["SUBMITTED": "بانتظار التأكيد", "CONFIRMED": "مؤكَّد", "DISPUTED": "معترَض عليه"]

    static func label(_ map: [String: String], _ value: String?) -> String {
        value.flatMap { map[$0] } ?? unmapped
    }
}

/// Arabic names for the job terms an offer can report as changed (jobs.models.WORKER_FACING_TERMS).
enum TermLabels {
    static let labels = [
        "work_date": "يوم العمل", "start_time": "وقت البداية", "end_time": "وقت النهاية",
        "location_city": "المدينة", "location_address": "العنوان", "wage_amount": "الأجر",
        "wage_basis": "طريقة احتساب الأجر", "description": "الوصف", "required_skills": "المهارات المطلوبة",
        "attendance_requirements": "شروط الحضور", "cancellation_policy": "سياسة الإلغاء",
        "additional_conditions": "شروط إضافية",
    ]

    /// "الأجر، يوم العمل"; a key this build does not know reads «شروط أخرى».
    static func changed(_ keys: [String]) -> String {
        var seen = Set<String>()
        return keys.map { labels[$0] ?? "شروط أخرى" }.filter { seen.insert($0).inserted }.joined(separator: "، ")
    }
}
