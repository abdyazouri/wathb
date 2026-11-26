package com.yawmiyati.app

import com.yawmiyati.app.data.api.PaymentAttemptInfo
import com.yawmiyati.app.data.api.PaymentInfoResponse
import com.yawmiyati.app.data.api.redactSecrets
import com.yawmiyati.app.data.wages.PaymentRepository
import com.yawmiyati.app.data.wages.PaymentResult
import com.yawmiyati.app.ui.components.extractSmsCode
import com.yawmiyati.app.viewmodels.WagePaymentViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** «تحويل الأجر»: screen states and keeping the code out of state and logs. */
@OptIn(ExperimentalCoroutinesApi::class)
class WagePaymentTest {

    private val dispatcher = StandardTestDispatcher()
    @Before fun setUp() { Dispatchers.setMain(dispatcher) }
    @After fun tearDown() { Dispatchers.resetMain() }

    private fun info(mode: String = "automatic", status: String = "DUE", attempt: PaymentAttemptInfo? = null,
                     needsWallet: Boolean = false) = PaymentInfoResponse(
        wageId = "w1", mode = mode, status = status, payable = status == "DUE", amount = 8500,
        amountDisplay = "٨٥ ₪", jobTitle = "Job", workerName = "عامل", workerWallet = "+970599000002",
        businessWallet = if (needsWallet) null else "+970599000009", needsWallet = needsWallet, attempt = attempt,
    )

    /** Server double: what it answers to each call; records the codes it received. */
    private inner class FakeServer : PaymentRepository() {
        var current = info()
        val codesSent = mutableListOf<String>()
        var nextSend: PaymentResult? = null
        var nextConfirm: PaymentResult? = null

        override suspend fun info(wageId: String) = PaymentResult.Success(current)
        override suspend fun send(wageId: String): PaymentResult = nextSend?.also { nextSend = null } ?: run {
            current = info(attempt = PaymentAttemptInfo("INITIATED", resendAvailableAt = "2026-12-01T09:01:00+02:00"))
            PaymentResult.Success(current)
        }
        override suspend fun confirm(wageId: String, code: String): PaymentResult {
            codesSent += code
            return nextConfirm?.also { nextConfirm = null } ?: run {
                current = info(status = "AWAITING_ACK", attempt = PaymentAttemptInfo("SUCCEEDED"))
                PaymentResult.Success(current)
            }
        }
        override suspend fun declareManual(wageId: String, reference: String): PaymentResult {
            current = info(mode = "manual", status = "AWAITING_ACK")
            return PaymentResult.Success(current)
        }
    }

    private fun vm(server: FakeServer) = WagePaymentViewModel(server, clock = { 1_000_000L })

    @Test
    fun `send then code pays and the code is not kept in state`() = runTest(dispatcher) {
        val server = FakeServer()
        val vm = vm(server)
        vm.load("w1"); advanceUntilIdle()
        assertFalse(vm.state.value.codeSent)
        vm.send(); advanceUntilIdle()
        assertTrue(vm.state.value.codeSent)
        assertEquals(java.time.OffsetDateTime.parse("2026-12-01T09:01:00+02:00").toInstant().toEpochMilli(),
            vm.state.value.resendAtMillis)
        vm.confirm("١٢٣ 456"); advanceUntilIdle()   // Arabic keyboard digits become 0–9
        assertEquals(listOf("123456"), server.codesSent)
        assertTrue(vm.state.value.paid)
        assertFalse(vm.state.value.toString().contains("123456"))
    }

    @Test
    fun `wrong code keeps waiting for the code with the server message`() = runTest(dispatcher) {
        val server = FakeServer()
        val vm = vm(server)
        vm.load("w1"); vm.send(); advanceUntilIdle()
        server.nextConfirm = PaymentResult.Error("الرمز غير صحيح.", failure = "WRONG_CODE")
        vm.confirm("654321"); advanceUntilIdle()
        assertEquals("الرمز غير صحيح.", vm.state.value.error)
        assertTrue(vm.state.value.codeSent)
        assertFalse(vm.state.value.paid)
    }

    @Test
    fun `too short a code is not sent`() = runTest(dispatcher) {
        val server = FakeServer()
        val vm = vm(server)
        vm.load("w1"); vm.send(); advanceUntilIdle()
        vm.confirm("12"); advanceUntilIdle()
        assertTrue(server.codesSent.isEmpty())
    }

    @Test
    fun `resend too early sets the countdown from the server`() = runTest(dispatcher) {
        val server = FakeServer()
        val vm = vm(server)
        vm.load("w1"); advanceUntilIdle()
        server.nextSend = PaymentResult.Error("يمكنك طلب رمز جديد بعد ٤٥ ثانية.", retryAfterSeconds = 45)
        vm.send(); advanceUntilIdle()
        assertEquals(1_000_000L + 45_000L, vm.state.value.resendAtMillis)
    }

    @Test
    fun `timeout asks to check the status instead of resending`() = runTest(dispatcher) {
        val server = FakeServer()
        val vm = vm(server)
        vm.load("w1"); vm.send(); advanceUntilIdle()
        server.nextConfirm = PaymentResult.Error("لم يصل رد.", timeout = true)
        server.current = info(attempt = PaymentAttemptInfo("UNKNOWN"))
        vm.confirm("123456"); advanceUntilIdle()
        assertTrue(vm.state.value.timeout)
        assertFalse(vm.state.value.paid)
    }

    @Test
    fun `manual mode declares and keeps no automatic state`() = runTest(dispatcher) {
        val server = FakeServer().apply { current = info(mode = "manual") }
        val vm = vm(server)
        vm.load("w1"); advanceUntilIdle()
        assertFalse(vm.state.value.codeSent)
        vm.declareManual("JP-1"); advanceUntilIdle()
        assertTrue(vm.state.value.paid)
        assertTrue(server.codesSent.isEmpty())
    }

    @Test
    fun `missing business wallet is reported`() = runTest(dispatcher) {
        val server = FakeServer().apply { current = info(needsWallet = true) }
        val vm = vm(server)
        vm.load("w1"); advanceUntilIdle()
        assertTrue(vm.state.value.needsWallet)
    }

    @Test
    fun `sms code is extracted from the message`() {
        assertEquals("482913", extractSmsCode("Jawwal Pay: رمز التأكيد 482913 صالح لمدة 5 دقائق"))
        assertNull(extractSmsCode("لا يوجد رمز هنا"))
        assertNull(extractSmsCode(null))
    }

    @Test
    fun `debug http logs mask the code, passwords and tokens`() {
        val line = """{"code":"482913","password":"s3cret","access":"eyJ.x","refresh":"eyJ.y","phone":"0599"}"""
        val redacted = redactSecrets(line)
        for (secret in listOf("482913", "s3cret", "eyJ.x", "eyJ.y")) assertFalse(redacted.contains(secret))
        assertTrue(redacted.contains("\"phone\":\"0599\""))
    }
}
