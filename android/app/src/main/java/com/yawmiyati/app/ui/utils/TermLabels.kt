package com.yawmiyati.app.ui.utils

/** Arabic names for the job terms an offer can report as changed (jobs.models.WORKER_FACING_TERMS). */
object TermLabels {
    internal val LABELS = mapOf(
        "work_date" to "يوم العمل",
        "start_time" to "وقت البداية",
        "end_time" to "وقت النهاية",
        "location_city" to "المدينة",
        "location_address" to "العنوان",
        "wage_amount" to "الأجر",
        "wage_basis" to "طريقة احتساب الأجر",
        "description" to "الوصف",
        "required_skills" to "المهارات المطلوبة",
        "attendance_requirements" to "شروط الحضور",
        "cancellation_policy" to "سياسة الإلغاء",
        "additional_conditions" to "شروط إضافية",
    )

    /** "الأجر، يوم العمل"; a key this build does not know reads «شروط أخرى». */
    fun changed(keys: List<String>): String =
        keys.map { LABELS[it] ?: "شروط أخرى" }.distinct().joinToString("، ")
}
