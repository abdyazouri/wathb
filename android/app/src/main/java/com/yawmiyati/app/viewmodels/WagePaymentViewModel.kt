package com.yawmiyati.app.viewmodels

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.yawmiyati.app.data.api.PaymentInfoResponse
import com.yawmiyati.app.data.wages.PaymentRepository
import com.yawmiyati.app.data.wages.PaymentResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.time.OffsetDateTime

/** "٤٨٢ 913" → "482913": an Arabic keyboard types Arabic-Indic digits; Jawwal Pay expects 0–9. */
internal fun String.toAsciiDigits(): String = buildString {
    for (c in this@toAsciiDigits) when (c) {
        in '0'..'9' -> append(c)
        in '٠'..'٩' -> append('0' + (c - '٠'))
        in '۰'..'۹' -> append('0' + (c - '۰'))
    }
}

/** «تحويل الأجر». Everything shown comes from the server; the code is never kept here. */
data class WagePaymentState(
    val loading: Boolean = true,
    val info: PaymentInfoResponse? = null,
    val busy: Boolean = false,
    val error: String? = null,
    val needsWallet: Boolean = false,
    val timeout: Boolean = false,          // Jawwal Pay did not answer: check status, never resend blindly
    val codeSent: Boolean = false,         // automatic mode: waiting for the SMS code
    val resendAtMillis: Long? = null,      // when «إعادة إرسال الرمز» is allowed
    val paid: Boolean = false,             // transferred (automatic) or declared (manual)
)

class WagePaymentViewModel(
    private val repository: PaymentRepository = PaymentRepository(),
    private val clock: () -> Long = System::currentTimeMillis,
) : ViewModel() {

    private val _state = MutableStateFlow(WagePaymentState())
    val state: StateFlow<WagePaymentState> = _state

    private var wageId: String? = null

    fun load(id: String) {
        wageId = id
        run(showBusy = false) { repository.info(id) }
    }

    /** «إرسال» (or «إعادة إرسال الرمز»): Jawwal Pay sends the business an SMS code. */
    fun send() = wageId?.let { id -> run { repository.send(id) } }

    /** Relays the code once. */
    fun confirm(code: String) = wageId?.let { id ->
        val digits = code.toAsciiDigits()
        if (digits.length < 4) {
            _state.value = _state.value.copy(error = "أدخل الرمز كما وصلك في الرسالة.")
            return@let
        }
        run { repository.confirm(id, digits) }
    }

    /** Manual mode «حوّلت الأجر». */
    fun declareManual(reference: String) = wageId?.let { id -> run { repository.declareManual(id, reference) } }

    fun dismissError() {
        _state.value = _state.value.copy(error = null)
    }

    private fun run(showBusy: Boolean = true, block: suspend () -> PaymentResult) {
        if (_state.value.busy) return
        _state.value = _state.value.copy(busy = showBusy, error = null, timeout = false)
        viewModelScope.launch {
            when (val result = block()) {
                is PaymentResult.Success -> apply(result.info)
                is PaymentResult.Error -> {
                    _state.value = _state.value.copy(
                        loading = false,
                        busy = false,
                        error = result.message,
                        timeout = result.timeout,
                        needsWallet = result.needsWallet || _state.value.needsWallet,
                        resendAtMillis = result.retryAfterSeconds?.let { clock() + it * 1000L } ?: _state.value.resendAtMillis,
                    )
                    // Re-read the server's view (attempt failed, already paid, …) but keep the message.
                    wageId?.let { id -> (repository.info(id) as? PaymentResult.Success)?.let { apply(it.info, keepError = true) } }
                }
            }
        }
    }

    private fun apply(info: PaymentInfoResponse, keepError: Boolean = false) {
        val attempt = info.attempt
        _state.value = _state.value.copy(
            loading = false,
            busy = false,
            info = info,
            error = if (keepError) _state.value.error else null,
            needsWallet = info.needsWallet,
            codeSent = info.payable && attempt?.status == "INITIATED",
            timeout = info.payable && attempt?.status == "UNKNOWN",
            resendAtMillis = attempt?.resendAvailableAt?.let {
                runCatching { OffsetDateTime.parse(it).toInstant().toEpochMilli() }.getOrNull()
            } ?: if (keepError) _state.value.resendAtMillis else null,
            paid = info.status == "AWAITING_ACK" || info.status == "VERIFIED_PAID",
        )
    }
}
