package com.yawmiyati.app

import com.yawmiyati.app.data.api.AssignmentResponse
import com.yawmiyati.app.data.api.JobApplicationResponse
import com.yawmiyati.app.viewmodels.MyApplicationsItem
import com.yawmiyati.app.viewmodels.canRequestWage
import com.yawmiyati.app.viewmodels.canWorkerCancel
import com.yawmiyati.app.viewmodels.splitMyWork
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime

/** A job sits in «طلباتي» until its start time, then moves to «مهامي». */
class MyWorkSplitTest {

    private val now = LocalDateTime.of(2026, 12, 1, 9, 0)

    private fun assignment(id: String, status: String, date: String = "2026-12-01", start: String = "08:00:00") =
        AssignmentResponse(
            id = id, job = "job-$id", jobTitle = "Job $id", workerPhone = "+970599000001",
            businessName = "Biz", jobWorkDate = date, jobStartTime = start, jobEndTime = "15:00:00",
            status = status, offeredAt = null, acceptedAt = null, cancelledAt = null, cancellationReason = "",
        )

    private fun application(id: String, status: String, job: String = "job-x-$id", assignmentId: String? = null) =
        JobApplicationResponse(
            id = id, job = job, jobTitle = "Job $id", status = status, coverNote = "",
            appliedAt = "2026-11-27T10:00:00Z", reviewedAt = null, assignmentId = assignmentId,
        )

    private fun ids(items: List<MyApplicationsItem>) = items.map {
        when (it) {
            is MyApplicationsItem.Offer -> "a:${it.assignment.id}"
            is MyApplicationsItem.Application -> "p:${it.application.id}"
        }
    }

    @Test
    fun `pending application stays in applications`() {
        val split = splitMyWork(listOf(application("1", "PENDING")), emptyList(), now)
        assertEquals(listOf("p:1"), ids(split.applications))
        assertTrue(split.tasks.isEmpty())
    }

    @Test
    fun `offer is shown in applications once, not twice`() {
        val offer = assignment("o", "OFFERED", date = "2026-12-05")
        val app = application("1", "OFFERED", job = offer.job, assignmentId = "o")
        val split = splitMyWork(listOf(app), listOf(offer), now)
        assertEquals(listOf("a:o"), ids(split.applications))
        assertTrue(split.tasks.isEmpty())
    }

    @Test
    fun `accepted job waits in applications until its start time`() {
        val before = assignment("a", "ACCEPTED", date = "2026-12-01", start = "09:30:00")
        assertEquals(listOf("a:a"), ids(splitMyWork(emptyList(), listOf(before), now).applications))

        val atStart = assignment("b", "ACCEPTED", date = "2026-12-01", start = "09:00:00")
        val split = splitMyWork(emptyList(), listOf(atStart), now)
        assertTrue(split.applications.isEmpty())
        assertEquals(listOf("b"), split.tasks.map { it.id })
    }

    @Test
    fun `active and completed jobs are tasks even with odd dates`() {
        val split = splitMyWork(
            emptyList(),
            listOf(assignment("x", "ACTIVE", date = "2030-01-01"), assignment("y", "COMPLETED", date = "2030-01-01")),
            now,
        )
        assertEquals(listOf("x", "y"), split.tasks.map { it.id })
    }

    @Test
    fun `declined offer and job cancelled before it started stay in applications`() {
        val split = splitMyWork(
            emptyList(),
            listOf(assignment("d", "DECLINED"), assignment("c", "CANCELLED", date = "2026-12-04")),
            now,
        )
        assertEquals(setOf("a:d", "a:c"), ids(split.applications).toSet())
        assertTrue(split.tasks.isEmpty())
    }

    @Test
    fun `offers first, then upcoming accepted soonest first, then pending, then closed`() {
        val split = splitMyWork(
            listOf(application("rej", "REJECTED"), application("pen", "PENDING")),
            listOf(
                assignment("late", "ACCEPTED", date = "2026-12-09"),
                assignment("soon", "ACCEPTED", date = "2026-12-02"),
                assignment("offer", "OFFERED", date = "2026-12-10"),
            ),
            now,
        )
        assertEquals(listOf("a:offer", "a:soon", "a:late", "p:pen", "p:rej"), ids(split.applications))
    }

    @Test
    fun `wage request button shows from the work date until the request is sent`() {
        val job = assignment("a", "ACCEPTED", date = "2026-12-03")
        assertFalse("before the work date", job.canRequestWage(LocalDate.of(2026, 12, 2)))
        assertTrue("on the work date", job.canRequestWage(LocalDate.of(2026, 12, 3)))
        assertTrue("worker forgot, next day", job.canRequestWage(LocalDate.of(2026, 12, 4)))
        val sent = job.copy(completionStatus = "SUBMITTED", completionRequestedByWorker = true)
        assertFalse("after the request is sent", sent.canRequestWage(LocalDate.of(2026, 12, 3)))
        assertFalse("business already recorded it", job.copy(completionStatus = "CONFIRMED").canRequestWage(LocalDate.of(2026, 12, 3)))
        for (s in listOf("OFFERED", "ACTIVE", "COMPLETED", "CANCELLED", "DECLINED")) {
            assertFalse(s, assignment("b", s, date = "2026-12-03").canRequestWage(LocalDate.of(2026, 12, 3)))
        }
    }

    @Test
    fun `worker can cancel only before the work day`() {
        val job = assignment("a", "ACCEPTED", date = "2026-12-03")
        assertTrue(job.canWorkerCancel(LocalDate.of(2026, 12, 2)))
        assertFalse(job.canWorkerCancel(LocalDate.of(2026, 12, 3)))
        assertFalse(assignment("b", "ACTIVE", date = "2026-12-03").canWorkerCancel(LocalDate.of(2026, 12, 1)))
    }
}
