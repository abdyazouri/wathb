package com.yawmiyati.app.data.wages

import com.yawmiyati.app.data.api.AcknowledgePaymentRequest
import com.yawmiyati.app.data.api.AdminVerifyDeclarationRequest
import com.yawmiyati.app.data.api.ApiClient
import com.yawmiyati.app.data.api.ApiErrors
import com.yawmiyati.app.data.api.DeclarePaymentRequest
import com.yawmiyati.app.data.api.DisputePaymentRequest
import com.yawmiyati.app.data.api.PaymentDeclarationResponse
import com.yawmiyati.app.data.api.WageObligationResponse

sealed class WageResult<out T> {
    data class Success<T>(val data: T) : WageResult<T>()
    data class Error(val message: String, val isAuth: Boolean = false) : WageResult<Nothing>()
}

open class WageRepository {
    private val api = ApiClient.wagesApi

    open suspend fun listObligations(status: String? = null): WageResult<List<WageObligationResponse>> {
        return try {
            val response = api.listObligations(status)
            if (response.isSuccessful) WageResult.Success(response.body()?.results ?: emptyList())
            else WageResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { WageResult.Error(networkMessage(e)) }
    }

    open suspend fun getObligation(id: String): WageResult<WageObligationResponse> {
        return try {
            val response = api.getObligation(id)
            if (response.isSuccessful) WageResult.Success(response.body()!!)
            else WageResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { WageResult.Error(networkMessage(e)) }
    }

    open suspend fun declarePayment(id: String, request: DeclarePaymentRequest): WageResult<PaymentDeclarationResponse> {
        return try {
            val response = api.declarePayment(id, request)
            if (response.isSuccessful) WageResult.Success(response.body()!!)
            else WageResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { WageResult.Error(networkMessage(e)) }
    }

    /** [password] is set only when the phone could not run BiometricPrompt. */
    open suspend fun acknowledgePayment(id: String, password: String? = null): WageResult<WageObligationResponse> {
        return try {
            val response = api.acknowledgePayment(id, AcknowledgePaymentRequest(password))
            if (response.isSuccessful) WageResult.Success(response.body()!!)
            else WageResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { WageResult.Error(networkMessage(e)) }
    }

    open suspend fun disputePayment(id: String, description: String): WageResult<WageObligationResponse> {
        return try {
            val response = api.disputePayment(id, DisputePaymentRequest(description = description))
            if (response.isSuccessful) WageResult.Success(response.body()!!)
            else WageResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { WageResult.Error(networkMessage(e)) }
    }

    open suspend fun verifyDeclaration(
        obligationId: String,
        declarationId: String,
        request: AdminVerifyDeclarationRequest
    ): WageResult<PaymentDeclarationResponse> {
        return try {
            val response = api.verifyDeclaration(obligationId, declarationId, request)
            if (response.isSuccessful) WageResult.Success(response.body()!!)
            else WageResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { WageResult.Error(networkMessage(e)) }
    }

    private fun parseError(body: String?): String = ApiErrors.message(body)

    private fun networkMessage(e: Exception): String = when {
        e is java.net.SocketTimeoutException -> "انتهت مهلة الاتصال بالخادم"
        e.message?.contains("Unable to resolve host") == true ||
            e.message?.contains("Failed to connect") == true -> "تعذّر الاتصال بالخادم"
        else -> e.localizedMessage ?: "خطأ في الشبكة"
    }
}
