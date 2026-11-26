package com.yawmiyati.app.data.auth

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

class TokenManager(context: Context) : TokenStore {
    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val prefs = EncryptedSharedPreferences.create(
        context,
        "yawmiyati_secure_prefs",
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )

    init {
        // Leftover from the removed fingerprint login (held the "biometric eligible" flag).
        context.deleteSharedPreferences("wathb_flags")
    }

    override fun saveTokens(access: String, refresh: String) {
        prefs.edit()
            .putString(KEY_ACCESS, access)
            .putString(KEY_REFRESH, refresh)
            .apply()
    }

    override fun getAccessToken(): String? = prefs.getString(KEY_ACCESS, null)
    override fun getRefreshToken(): String? = prefs.getString(KEY_REFRESH, null)

    fun saveRole(role: String) {
        prefs.edit().putString(KEY_ROLE, role).apply()
    }

    fun getRole(): String? = prefs.getString(KEY_ROLE, null)

    fun isLoggedIn(): Boolean = getAccessToken() != null

    /**
     * The user chose to open the app with fingerprint/face (or the screen lock).
     * Kept with the session in encrypted prefs and wiped by [clear], so after logging out
     * or an expired session the password is needed again.
     */
    fun isBiometricLoginEnabled(): Boolean = prefs.getBoolean(KEY_BIOMETRIC_LOGIN, false)

    fun setBiometricLoginEnabled(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_BIOMETRIC_LOGIN, enabled).apply()
    }

    /** Full logout — clears everything. */
    override fun clear() {
        prefs.edit()
            .remove(KEY_ACCESS)
            .remove(KEY_REFRESH)
            .remove(KEY_ROLE)
            .remove(KEY_BIOMETRIC_LOGIN)
            .apply()
    }

    companion object {
        private const val KEY_ACCESS  = "access_token"
        private const val KEY_REFRESH = "refresh_token"
        private const val KEY_ROLE    = "user_role"
        private const val KEY_BIOMETRIC_LOGIN = "biometric_login_enabled"
    }
}
