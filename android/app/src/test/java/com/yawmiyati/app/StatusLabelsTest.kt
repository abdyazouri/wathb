package com.yawmiyati.app

import com.yawmiyati.app.ui.utils.StatusLabels
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/** No screen may show a raw status value: every server status has an Arabic label. */
class StatusLabelsTest {

    private val logged = mutableListOf<Pair<String, String?>>()

    @Before fun captureLog() { StatusLabels.logUnmapped = { kind, value -> logged += kind to value } }
    @After fun restoreLog() { StatusLabels.logUnmapped = { _, _ -> } }

    /** Reads `class <name>(models.TextChoices)` values from the backend source next door. */
    private fun serverValues(app: String, choices: String): List<String> {
        val models = File("../../backend/$app/models.py")
        assumeTrue("backend source not found at ${models.absolutePath}", models.exists())
        val body = models.readText()
            .substringAfter("class $choices(models.TextChoices):")
            .substringBefore("\nclass ")
        return Regex("""^\s+[A-Z_]+\s*=\s*"([A-Z_]+)"""", RegexOption.MULTILINE)
            .findAll(body).map { it.groupValues[1] }.toList()
            .also { assertTrue("no values parsed for $choices", it.isNotEmpty()) }
    }

    private fun assertAllMapped(values: List<String>, label: (String) -> String) {
        for (v in values) {
            val text = label(v)
            assertTrue("$v is unmapped", text != StatusLabels.UNMAPPED)
            assertTrue("$v label is not Arabic: $text", text.any { it in '؀'..'ۿ' })
        }
        assertEquals(emptyList<Pair<String, String?>>(), logged)
    }

    @Test fun `every job status has a label`() =
        assertAllMapped(serverValues("jobs", "JobListingStatus"), StatusLabels::job)

    @Test fun `every application status has a label in both lists`() {
        val values = serverValues("jobs", "ApplicationStatus")
        assertTrue("EXPIRED" in values && "CANCELLED" in values)
        assertAllMapped(values, StatusLabels::applicationForBusiness)
        assertAllMapped(values, StatusLabels::applicationForWorker)
    }

    @Test fun `every assignment status has a label`() =
        assertAllMapped(serverValues("assignments", "AssignmentStatus"), StatusLabels::assignment)

    @Test fun `every wage status has a label for business and worker`() {
        val values = serverValues("wages", "WageObligationStatus")
        assertTrue("DECLARED" in values && "CANCELLED" in values)
        assertAllMapped(values, StatusLabels::wageForBusiness)
        assertAllMapped(values, StatusLabels::wageForWorker)
    }

    @Test fun `every dispute status has a label`() =
        assertAllMapped(serverValues("disputes", "DisputeStatus"), StatusLabels::dispute)

    @Test fun `every verification status has a label for admin and owner`() {
        val values = serverValues("accounts", "VerificationStatus")
        assertAllMapped(values, StatusLabels::verificationForAdmin)
        assertAllMapped(values, StatusLabels::verificationForOwner)
    }

    @Test fun `unknown value shows the neutral Arabic fallback and is logged`() {
        assertEquals(StatusLabels.UNMAPPED, StatusLabels.wageForWorker("SOMETHING_NEW"))
        assertEquals(StatusLabels.UNMAPPED, StatusLabels.applicationForWorker(null))
        assertEquals(listOf("wage" to "SOMETHING_NEW", "application" to null), logged)
    }
}
