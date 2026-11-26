package com.yawmiyati.app.data.auth

import com.yawmiyati.app.data.api.ApiClient
import com.yawmiyati.app.data.api.ApiErrors
import com.yawmiyati.app.data.api.DeleteAccountRequest
import com.yawmiyati.app.data.api.LoginRequest
import com.yawmiyati.app.data.api.RefreshRequest
import com.yawmiyati.app.data.api.RegisterBusinessRequest
import com.yawmiyati.app.data.api.RegisterWorkerRequest
import com.yawmiyati.app.data.api.UserResponse

sealed class AuthResult<out T> {
    data class Success<T>(val data: T) : AuthResult<T>()
    data class Error(val message: String) : AuthResult<Nothing>()
}

class AuthRepository(private val tokenManager: TokenManager) {
    private val api = ApiClient.authApi

    suspend fun login(phone: String, password: String): AuthResult<UserResponse> {
        return try {
            val response = api.login(LoginRequest(phone, password))
            if (response.isSuccessful) {
                val body = response.body()!!
                tokenManager.saveTokens(body.access, body.refresh)
                val meResponse = api.me()
                if (meResponse.isSuccessful) {
                    val user = meResponse.body()!!
                    tokenManager.saveRole(user.role)
                    AuthResult.Success(user)
                } else {
                    AuthResult.Error("تعذّر تحميل ملف المستخدم")
                }
            } else {
                AuthResult.Error(parseErrorMessage(response.errorBody()?.string()))
            }
        } catch (e: Exception) {
            AuthResult.Error(networkMessage(e))
        }
    }

    suspend fun registerWorker(
        phone: String, password: String, fullName: String, consentVersion: Int
    ): AuthResult<UserResponse> {
        return try {
            val response = api.registerWorker(
                RegisterWorkerRequest(phone, password, fullName = fullName,
                    consentVersion = consentVersion)
            )
            if (response.isSuccessful) {
                val body = response.body()!!
                // Registration returns tokens — save them so user is logged in immediately
                tokenManager.saveTokens(body.access, body.refresh)
                tokenManager.saveRole(body.user.role)
                AuthResult.Success(body.user)
            } else {
                AuthResult.Error(parseErrorMessage(response.errorBody()?.string()))
            }
        } catch (e: Exception) {
            AuthResult.Error(networkMessage(e))
        }
    }

    suspend fun registerBusiness(
        phone: String, password: String,
        legalName: String, contactName: String, contactPhone: String, consentVersion: Int
    ): AuthResult<UserResponse> {
        return try {
            val response = api.registerBusiness(
                RegisterBusinessRequest(
                    phone, password,
                    legalName = legalName,
                    contactName = contactName,
                    contactPhone = contactPhone,
                    consentVersion = consentVersion
                )
            )
            if (response.isSuccessful) {
                val body = response.body()!!
                tokenManager.saveTokens(body.access, body.refresh)
                tokenManager.saveRole(body.user.role)
                AuthResult.Success(body.user)
            } else {
                AuthResult.Error(parseErrorMessage(response.errorBody()?.string()))
            }
        } catch (e: Exception) {
            AuthResult.Error(networkMessage(e))
        }
    }

    /** POST /auth/delete-account/ — returns Success(Unit) on 204 (tokens already cleared),
     *  or Error with the server's Arabic `detail` on 403 (wrong password) / 409 (blockers). */
    suspend fun deleteAccount(password: String): AuthResult<Unit> {
        return try {
            val response = api.deleteAccount(DeleteAccountRequest(password))
            if (response.isSuccessful) {
                tokenManager.clear()
                AuthResult.Success(Unit)
            } else {
                AuthResult.Error(parseErrorMessage(response.errorBody()?.string()))
            }
        } catch (e: Exception) {
            AuthResult.Error(networkMessage(e))
        }
    }

    /**
     * Full logout: blacklists the refresh token on the server, then wipes all local tokens.
     * The user must re-enter their password next time.
     */
    suspend fun logout() {
        val refresh = tokenManager.getRefreshToken()
        if (refresh != null) {
            try { api.logout(RefreshRequest(refresh)) } catch (_: Exception) {}
        }
        tokenManager.clear()
    }

    private fun parseErrorMessage(body: String?): String = ApiErrors.message(body)

    private fun networkMessage(e: Exception): String = when {
        e is java.net.SocketTimeoutException -> "انتهت مهلة الاتصال بالخادم"
        e.message?.contains("Unable to resolve host") == true ||
            e.message?.contains("Failed to connect") == true -> "تعذّر الاتصال بالخادم"
        else -> e.localizedMessage ?: "خطأ في الشبكة"
    }
}
