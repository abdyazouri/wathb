package com.yawmiyati.app

import com.google.gson.Gson
import com.yawmiyati.app.data.api.AcknowledgePaymentRequest
import com.yawmiyati.app.data.api.WageObligationResponse
import com.yawmiyati.app.data.wages.WageRepository
import com.yawmiyati.app.data.wages.WageResult
import com.yawmiyati.app.ui.components.AcknowledgeAuth
import com.yawmiyati.app.ui.components.acknowledgeAuthFor
import com.yawmiyati.app.viewmodels.WageActionState
import com.yawmiyati.app.viewmodels.WorkerWagesViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

/** "استلمت" needs BiometricPrompt, or the account password on a phone without one. */
@OptIn(ExperimentalCoroutinesApi::class)
class AcknowledgeAuthTest {

    private val testDispatcher = StandardTestDispatcher()

    @Before fun setUp() { Dispatchers.setMain(testDispatcher) }
    @After  fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun `phone with fingerprint or screen lock uses the device prompt`() {
        assertEquals(AcknowledgeAuth.DEVICE_PROMPT, acknowledgeAuthFor(deviceAuthAvailable = true))
    }

    @Test
    fun `phone with neither asks for the account password`() {
        assertEquals(AcknowledgeAuth.ACCOUNT_PASSWORD, acknowledgeAuthFor(deviceAuthAvailable = false))
    }

    @Test
    fun `request body carries the password only when given`() {
        assertEquals("{}", Gson().toJson(AcknowledgePaymentRequest()))
        assertEquals("""{"password":"s3cret"}""", Gson().toJson(AcknowledgePaymentRequest("s3cret")))
    }

    @Test
    fun `view model passes the password through and shows the server's 403 detail`() = runTest(testDispatcher) {
        val obligation = WageObligationResponse(
            id = "o-1", assignment = "a-1", workerPhone = "+970599000001",
            jobTitle = "Day Work", amount = 10000L, currency = "ILS",
            amountDisplay = "100 ILS", dueDate = "2026-10-15", status = "AWAITING_ACK",
            createdAt = "2026-10-10T08:00:00Z", declarations = emptyList()
        )
        val sent = mutableListOf<String?>()
        val repo = object : WageRepository() {
            override suspend fun listObligations(status: String?) = WageResult.Success(listOf(obligation))
            override suspend fun acknowledgePayment(id: String, password: String?): WageResult<WageObligationResponse> {
                sent += password
                return WageResult.Error("كلمة المرور غير صحيحة.")
            }
        }
        val vm = WorkerWagesViewModel(repo)
        advanceUntilIdle()

        vm.acknowledgePayment("o-1", "wrong")
        advanceUntilIdle()

        assertEquals(listOf<String?>("wrong"), sent)
        assertEquals(WageActionState.Error("كلمة المرور غير صحيحة."), vm.actionState.value)
    }
}
