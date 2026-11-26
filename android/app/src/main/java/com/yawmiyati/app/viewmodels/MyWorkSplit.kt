package com.yawmiyati.app.viewmodels

import com.yawmiyati.app.data.api.AssignmentResponse
import com.yawmiyati.app.data.api.JobApplicationResponse
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId

/** Work dates and times are Gaza local time on the server (TIME_ZONE = "Asia/Gaza"). */
val GAZA: ZoneId = ZoneId.of("Asia/Gaza")

fun nowInGaza(): LocalDateTime = LocalDateTime.now(GAZA)

/** When the job starts: work date + start time. Null if the server did not send them. */
fun AssignmentResponse.workStart(): LocalDateTime? = try {
    val date = LocalDate.parse(jobWorkDate?.take(10) ?: return null)
    val time = LocalTime.parse(jobStartTime?.take(5) ?: return null)
    LocalDateTime.of(date, time)
} catch (_: Exception) {
    null
}

fun AssignmentResponse.hasStarted(now: LocalDateTime): Boolean = workStart()?.let { !now.isBefore(it) } ?: true

/** The server lets a worker cancel only before the work day. */
fun AssignmentResponse.canWorkerCancel(today: LocalDate): Boolean =
    status == "ACCEPTED" && jobWorkDate?.let { runCatching { today.isBefore(LocalDate.parse(it.take(10))) }.getOrNull() } == true

/**
 * «أتممت يوم عملي واطلب أجري»: on an accepted job, from the start of its work date (Gaza),
 * until someone has recorded completion.
 */
fun AssignmentResponse.canRequestWage(today: LocalDate): Boolean =
    status == "ACCEPTED" && completionStatus == null && workDayReached(today)

/** The work date has come (Gaza time). */
fun AssignmentResponse.workDayReached(today: LocalDate): Boolean =
    jobWorkDate?.let { runCatching { !today.isBefore(LocalDate.parse(it.take(10))) }.getOrNull() } == true

/** One row of «طلباتي»: either an offer/accepted job (assignment) or a plain application. */
sealed class MyApplicationsItem {
    data class Offer(val assignment: AssignmentResponse) : MyApplicationsItem()
    data class Application(val application: JobApplicationResponse) : MyApplicationsItem()
}

data class MyWorkSplit(
    /** From applying until the work starts. */
    val applications: List<MyApplicationsItem>,
    /** From the start time on: attendance, finishing the job, the wage. */
    val tasks: List<AssignmentResponse>,
)

/**
 * «طلباتي» holds everything before the work starts: pending/closed applications, offers
 * (accept or decline) and accepted jobs whose start time has not come yet.
 * «مهامي» holds a job from its start time (work date + start time, Gaza time) onward.
 */
fun splitMyWork(
    applications: List<JobApplicationResponse>,
    assignments: List<AssignmentResponse>,
    now: LocalDateTime,
): MyWorkSplit {
    val (tasks, beforeWork) = assignments.partition { a ->
        when (a.status) {
            "OFFERED", "DECLINED" -> false
            "ACTIVE", "COMPLETED" -> true
            else -> a.hasStarted(now)  // ACCEPTED, CANCELLED
        }
    }
    // An application that led to an offer is shown once, as the offer/assignment.
    val withAssignment = assignments.map { it.id }.toSet()
    val jobsWithAssignment = assignments.map { it.job }.toSet()
    val plainApplications = applications.filter { app ->
        app.assignmentId?.let { it !in withAssignment } ?: (app.job !in jobsWithAssignment)
    }

    val offerOrder = mapOf("OFFERED" to 0, "ACCEPTED" to 1, "CANCELLED" to 3, "DECLINED" to 3)
    val appOrder = mapOf("PENDING" to 2)
    val items = beforeWork.map { MyApplicationsItem.Offer(it) } + plainApplications.map { MyApplicationsItem.Application(it) }
    val sortedItems = items.sortedWith(
        compareBy<MyApplicationsItem> {
            when (it) {
                is MyApplicationsItem.Offer -> offerOrder[it.assignment.status] ?: 3
                is MyApplicationsItem.Application -> appOrder[it.application.status] ?: 3
            }
        }.thenBy {
            // Upcoming jobs soonest first.
            (it as? MyApplicationsItem.Offer)?.assignment?.workStart() ?: LocalDateTime.MAX
        }
    )

    val taskOrder = mapOf("ACTIVE" to 0, "ACCEPTED" to 0, "COMPLETED" to 1, "CANCELLED" to 2)
    val sortedTasks = tasks.sortedWith(
        compareBy<AssignmentResponse> { taskOrder[it.status] ?: 2 }
            .thenByDescending { it.workStart() ?: LocalDateTime.MIN }
    )
    return MyWorkSplit(sortedItems, sortedTasks)
}
