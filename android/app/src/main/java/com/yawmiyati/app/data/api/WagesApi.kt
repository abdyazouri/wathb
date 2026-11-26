package com.yawmiyati.app.data.api

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface WagesApi {
    @GET("wages/")
    suspend fun listObligations(
        @Query("status") status: String? = null
    ): Response<PaginatedResponse<WageObligationResponse>>

    @GET("wages/{id}/")
    suspend fun getObligation(@Path("id") id: String): Response<WageObligationResponse>

    @POST("wages/{id}/declare-payment/")
    suspend fun declarePayment(
        @Path("id") id: String,
        @Body request: DeclarePaymentRequest
    ): Response<PaymentDeclarationResponse>

    @POST("wages/{id}/acknowledge/")
    suspend fun acknowledgePayment(
        @Path("id") id: String,
        @Body request: AcknowledgePaymentRequest
    ): Response<WageObligationResponse>

    @POST("wages/{id}/dispute-payment/")
    suspend fun disputePayment(
        @Path("id") id: String,
        @Body request: DisputePaymentRequest
    ): Response<WageObligationResponse>

    @GET("wages/{id}/payment/")
    suspend fun getPayment(@Path("id") id: String): Response<PaymentInfoResponse>

    @POST("wages/{id}/payment/initiate/")
    suspend fun initiatePayment(@Path("id") id: String): Response<PaymentInfoResponse>

    @POST("wages/{id}/payment/confirm/")
    suspend fun confirmPayment(@Path("id") id: String, @Body request: PaymentCodeRequest): Response<PaymentInfoResponse>

    @POST("wages/{id}/declarations/{decId}/verify/")
    suspend fun verifyDeclaration(
        @Path("id") id: String,
        @Path("decId") decId: String,
        @Body request: AdminVerifyDeclarationRequest
    ): Response<PaymentDeclarationResponse>
}
