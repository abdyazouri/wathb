package com.yawmiyati.app.ui.utils

import android.util.Log

/**
 * Arabic label for every status value the server sends. A value missing here never
 * reaches the screen: it shows [UNMAPPED] and is logged so it can be added.
 * Keep in sync with the TextChoices in each backend app's models.py (StatusLabelsTest checks).
 */
object StatusLabels {
    const val UNMAPPED = "غير محدد"

    /** Replaced in JVM tests, where android.util.Log is not available. */
    internal var logUnmapped: (kind: String, value: String?) -> Unit = { kind, value ->
        Log.w("WATHB_STATUS", "Unmapped $kind status: $value")
    }

    private fun label(kind: String, labels: Map<String, String>, value: String?): String =
        labels[value] ?: UNMAPPED.also { logUnmapped(kind, value) }

    // jobs.JobListingStatus
    internal val JOB = mapOf(
        "DRAFT" to "مسودة",
        "PENDING_REVIEW" to "قيد المراجعة",
        "PUBLISHED" to "منشور",
        "FILLED" to "اكتمل العدد",
        "IN_PROGRESS" to "قيد التنفيذ",
        "COMPLETED" to "منتهية",
        "CANCELLED" to "ملغاة",
    )

    // jobs.ApplicationStatus, as the business sees an applicant
    internal val APPLICATION_FOR_BUSINESS = mapOf(
        "PENDING" to "معلق",
        "OFFERED" to "عُرض عليه",
        "ACCEPTED" to "قبل",
        "REJECTED" to "مرفوض",
        "WITHDRAWN" to "انسحب",
        "EXPIRED" to "انتهت المهلة",
        "CANCELLED" to "ملغى",
    )

    // jobs.ApplicationStatus, as the worker sees their own application
    internal val APPLICATION_FOR_WORKER = mapOf(
        "PENDING" to "معلّق",
        "OFFERED" to "معروض",
        "ACCEPTED" to "مقبول",
        "REJECTED" to "مرفوض",
        "WITHDRAWN" to "مسحوب",
        "EXPIRED" to "انتهت المهلة",
        "CANCELLED" to "ملغى",
    )

    // assignments.AssignmentStatus
    internal val ASSIGNMENT = mapOf(
        "OFFERED" to "عرض جديد",
        "ACCEPTED" to "مقبول",
        "DECLINED" to "مرفوض",
        "ACTIVE" to "نشط",
        "COMPLETED" to "مكتمل",
        "CANCELLED" to "ملغى",
    )

    // wages.WageObligationStatus, business view
    internal val WAGE_FOR_BUSINESS = mapOf(
        "PENDING" to "معلق",
        "DUE" to "مستحق",
        "DECLARED" to "تم الإعلان",
        "AWAITING_ACK" to "بانتظار التأكيد",
        "UNDER_REVIEW" to "قيد المراجعة",
        "DISPUTED" to "متنازع عليه",
        "VERIFIED_PAID" to "مدفوع ومؤكد",
        "REJECTED" to "مرفوض",
        "CANCELLED" to "ملغى",
    )

    // wages.WageObligationStatus, worker view
    internal val WAGE_FOR_WORKER = WAGE_FOR_BUSINESS + mapOf(
        "DECLARED" to "أُعلن الدفع",
        "AWAITING_ACK" to "بانتظار تأكيدك",
    )

    // assignments.AttendanceStatus
    internal val ATTENDANCE = mapOf(
        "SUBMITTED" to "بانتظار التأكيد",
        "CONFIRMED" to "مؤكَّد",
        "DISPUTED" to "معترَض عليه",
        "CANCELLED" to "ملغى",
    )

    // assignments.CompletionStatus
    internal val COMPLETION = mapOf(
        "SUBMITTED" to "بانتظار التأكيد",
        "CONFIRMED" to "مؤكَّد",
        "DISPUTED" to "معترَض عليه",
    )

    // disputes.DisputeStatus
    internal val DISPUTE = mapOf(
        "OPEN" to "مفتوح",
        "IN_REVIEW" to "قيد المراجعة",
        "RESOLVED" to "محلول",
        "CLOSED" to "مغلق",
    )

    // accounts.VerificationStatus, admin view
    internal val VERIFICATION_FOR_ADMIN = mapOf(
        "PENDING" to "معلق",
        "APPROVED" to "موافق عليه",
        "REJECTED" to "مرفوض",
        "SUSPENDED" to "موقوف",
    )

    // accounts.VerificationStatus, as the business owner sees their profile
    internal val VERIFICATION_FOR_OWNER = mapOf(
        "PENDING" to "في انتظار التحقق",
        "APPROVED" to "موثّق ✓",
        "REJECTED" to "مرفوض",
        "SUSPENDED" to "موقوف",
    )

    fun job(status: String?) = label("job", JOB, status)
    fun applicationForBusiness(status: String?) = label("application", APPLICATION_FOR_BUSINESS, status)
    fun applicationForWorker(status: String?) = label("application", APPLICATION_FOR_WORKER, status)
    fun assignment(status: String?) = label("assignment", ASSIGNMENT, status)
    fun wageForBusiness(status: String?) = label("wage", WAGE_FOR_BUSINESS, status)
    fun wageForWorker(status: String?) = label("wage", WAGE_FOR_WORKER, status)
    fun attendance(status: String?) = label("attendance", ATTENDANCE, status)
    fun completion(status: String?) = label("completion", COMPLETION, status)
    fun dispute(status: String?) = label("dispute", DISPUTE, status)
    fun verificationForAdmin(status: String?) = label("verification", VERIFICATION_FOR_ADMIN, status)
    fun verificationForOwner(status: String?) = label("verification", VERIFICATION_FOR_OWNER, status)
}
