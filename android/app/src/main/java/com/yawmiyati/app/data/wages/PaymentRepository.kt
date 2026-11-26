package com.yawmiyati.app.data.wages

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.yawmiyati.app.data.api.ApiClient
import com.yawmiyati.app.data.api.ApiErrors
import com.yawmiyati.app.data.api.DeclarePaymentRequest
import com.yawmiyati.app.data.api.PaymentCodeRequest
import com.yawmiyati.app.data.api.PaymentInfoResponse
import com.yawmiyati.app.data.api.SessionRefreshUnavailableException
import retrofit2.Response

sealed class PaymentResult {
    data class Success(val info: PaymentInfoResponse) : PaymentResult()
    data class Error(
        val message: String,
        val failure: String? = null,          // WRONG_CODE, CODE_EXPIRED, INSUFFICIENT_BALANCE, …
        val retryAfterSeconds: Int? = null,   // code re-send not allowed yet
        val needsWallet: Boolean = false,
        val timeout: Boolean = false,         // no answer from Jawwal Pay: check status, never retry blindly
        val alreadyPaid: Boolean = false,
    ) : PaymentResult()
}

/** «تحويل الأجر». The code passed to [confirm] is sent once and never kept or logged. */
open class PaymentRepository {
    private val api = ApiClient.wagesApi

    open suspend fun info(wageId: String) = call { api.getPayment(wageId) }
    open suspend fun send(wageId: String) = call { api.initiatePayment(wageId) }
    open suspend fun confirm(wageId: String, code: String) = call { api.confirmPayment(wageId, PaymentCodeRequest(code)) }

    /** Manual mode «حوّلت الأجر», then reload the screen. */
    open suspend fun declareManual(wageId: String, reference: String): PaymentResult {
        return try {
            val response = api.declarePayment(wageId, DeclarePaymentRequest(reference.trim()))
            if (response.isSuccessful) info(wageId) else error(response)
        } catch (e: Exception) {
            PaymentResult.Error(networkMessage(e))
        }
    }

    private suspend fun call(block: suspend () -> Response<PaymentInfoResponse>): PaymentResult {
        return try {
            val response = block()
            val body = response.body()
            if (response.isSuccessful && body != null) PaymentResult.Success(body) else error(response)
        } catch (e: Exception) {
            PaymentResult.Error(networkMessage(e))
        }
    }

    private fun error(response: Response<*>): PaymentResult.Error {
        val raw = response.errorBody()?.string()
        val json = runCatching { Gson().fromJson(raw, JsonObject::class.java) }.getOrNull()
        return PaymentResult.Error(
            message = ApiErrors.message(raw),
            failure = json?.get("failure")?.takeIf { !it.isJsonNull }?.asString,
            retryAfterSeconds = json?.get("retry_after")?.takeIf { !it.isJsonNull }?.asInt,
            needsWallet = json?.get("needs_wallet")?.takeIf { !it.isJsonNull }?.asBoolean == true,
            timeout = response.code() == 504,
            alreadyPaid = response.code() == 409 && json?.has("wage_id") == true,
        )
    }

    private fun networkMessage(e: Exception): String =
        if (e is SessionRefreshUnavailableException) e.message!!
        else "تعذّر الاتصال بالخادم. تحقّق من الإنترنت ثم حاول مرة أخرى."
}
