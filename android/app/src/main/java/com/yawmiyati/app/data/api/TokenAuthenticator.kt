package com.yawmiyati.app.data.api

import com.yawmiyati.app.data.auth.SessionEventBus
import com.yawmiyati.app.data.auth.TokenStore
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.Authenticator
import okhttp3.Request
import okhttp3.Response
import okhttp3.Route
import java.io.IOException

/**
 * Thrown from [TokenAuthenticator] when the refresh call could not reach a verdict
 * (no connection, timeout, 5xx). The session is kept; repositories surface [message]
 * through their normal `catch (e: Exception)` path so the user can retry.
 */
class SessionRefreshUnavailableException(cause: Throwable? = null) :
    IOException(NO_CONNECTION_MESSAGE, cause) {
    companion object {
        const val NO_CONNECTION_MESSAGE = "تعذّر الاتصال بالخادم. تحقّق من الإنترنت ثم حاول مرة أخرى."
    }
}

class TokenAuthenticator(
    private val tokenStore: TokenStore,
    private val refreshApi: AuthApi,
    private val mutex: Mutex = Mutex()
) : Authenticator {

    override fun authenticate(route: Route?, response: Response): Request? {
        val staleToken = response.request.header("Authorization")
            ?.removePrefix("Bearer ")
            ?: return null

        return runBlocking {
            mutex.withLock {
                val currentToken = tokenStore.getAccessToken()
                // Another coroutine already refreshed — retry with the new token.
                if (currentToken != null && currentToken != staleToken) {
                    return@withLock response.request.newBuilder()
                        .header("Authorization", "Bearer $currentToken")
                        .build()
                }

                val refreshToken = tokenStore.getRefreshToken()
                if (refreshToken.isNullOrBlank()) {
                    signOut()
                    return@withLock null
                }

                val result = try {
                    refreshApi.refreshToken(RefreshRequest(refreshToken))
                } catch (e: Exception) {
                    // Network error or timeout: no verdict on the token, keep the session.
                    throw SessionRefreshUnavailableException(e)
                }

                val body = result.body()
                when {
                    result.isSuccessful && body != null -> {
                        tokenStore.saveTokens(body.access, body.refresh ?: refreshToken)
                        response.request.newBuilder()
                            .header("Authorization", "Bearer ${body.access}")
                            .build()
                    }
                    isRefreshTokenRejected(result.code()) -> {
                        signOut()
                        null
                    }
                    // 5xx, 429, a proxy page…: the server never judged the token.
                    else -> throw SessionRefreshUnavailableException()
                }
            }
        }
    }

    companion object {
        /** Only these mean the server looked at the refresh token and refused it
         *  (expired, invalid or blacklisted). Everything else keeps the session. */
        fun isRefreshTokenRejected(code: Int): Boolean = code == 401 || code == 400
    }

    private fun signOut() {
        tokenStore.clear()
        SessionEventBus.emitSessionExpired()
    }
}
