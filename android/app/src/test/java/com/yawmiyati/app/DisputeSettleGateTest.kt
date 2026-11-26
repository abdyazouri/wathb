package com.yawmiyati.app

import com.yawmiyati.app.data.api.DisputeResponse
import com.yawmiyati.app.viewmodels.canSettleWage
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** "الدفع تم" / "الدفع لم يتم" appear only for an open dispute on a still-disputed wage. */
class DisputeSettleGateTest {

    private fun dispute(
        status: String = "OPEN",
        wage: String? = "wage-1",
        wageStatus: String? = "DISPUTED",
        declaration: String? = "dec-1",
    ) = DisputeResponse(
        id = "d-1", category = "PAYMENT_NOT_RECEIVED", assignment = "a-1",
        wageObligation = wage, wageObligationStatus = wageStatus, disputedDeclaration = declaration,
        raisedByPhone = "+970599000001", description = "", status = status,
        createdAt = "2026-11-20T00:00:00Z",
    )

    @Test
    fun `open or in-review dispute on a disputed wage can be settled`() {
        assertTrue(dispute(status = "OPEN").canSettleWage)
        assertTrue(dispute(status = "IN_REVIEW").canSettleWage)
    }

    @Test
    fun `dispute not about a wage cannot be settled`() {
        assertFalse(dispute(wage = null, wageStatus = null, declaration = null).canSettleWage)
    }

    @Test
    fun `wage no longer disputed cannot be settled`() {
        for (s in listOf("AWAITING_ACK", "DUE", "VERIFIED_PAID", "PENDING", "REJECTED", null)) {
            assertFalse(s.toString(), dispute(wageStatus = s).canSettleWage)
        }
        assertFalse(dispute(declaration = null).canSettleWage)
    }

    @Test
    fun `resolved or closed dispute cannot be settled`() {
        assertFalse(dispute(status = "RESOLVED").canSettleWage)
        assertFalse(dispute(status = "CLOSED").canSettleWage)
    }
}
