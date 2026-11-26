package com.yawmiyati.app

import com.yawmiyati.app.ui.utils.TermLabels
import org.junit.Assert.assertEquals
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

class TermLabelsTest {

    @Test
    fun `every term the server can report has an Arabic name`() {
        val models = File("../../backend/jobs/models.py")
        assumeTrue("backend source not found", models.exists())
        val tuple = models.readText().substringAfter("WORKER_FACING_TERMS = (").substringBefore(")")
        val keys = Regex(""""([a-z_]+)"""").findAll(tuple).map { it.groupValues[1] }.toList()
        assertEquals(keys.toSet(), TermLabels.LABELS.keys)
    }

    @Test
    fun `changed terms read as one Arabic line`() {
        assertEquals("يوم العمل، الأجر", TermLabels.changed(listOf("work_date", "wage_amount")))
        assertEquals("الأجر، شروط أخرى", TermLabels.changed(listOf("wage_amount", "something_new")))
    }
}
