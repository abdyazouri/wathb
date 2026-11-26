package com.yawmiyati.app.viewmodels

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.yawmiyati.app.YawmiyatiApp
import com.yawmiyati.app.data.api.UserResponse
import com.yawmiyati.app.data.auth.AuthRepository
import com.yawmiyati.app.data.auth.AuthResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

sealed class AuthUiState {
    object Idle : AuthUiState()
    object Loading : AuthUiState()
    data class Success(val user: UserResponse) : AuthUiState()
    data class Error(val message: String) : AuthUiState()
    object LoggedOut : AuthUiState()
}

sealed class DeleteAccountState {
    object Idle : DeleteAccountState()
    object Loading : DeleteAccountState()
    object Success : DeleteAccountState()
    data class Error(val message: String) : DeleteAccountState()
}

class AuthViewModel : ViewModel() {
    private val tokenManager = YawmiyatiApp.instance.tokenManager
    private val repository = AuthRepository(tokenManager)

    private val _uiState = MutableStateFlow<AuthUiState>(AuthUiState.Idle)
    val uiState: StateFlow<AuthUiState> = _uiState

    private val _deleteState = MutableStateFlow<DeleteAccountState>(DeleteAccountState.Idle)
    val deleteState: StateFlow<DeleteAccountState> = _deleteState

    private val _biometricLoginEnabled = MutableStateFlow(tokenManager.isBiometricLoginEnabled())
    /** Open the app with fingerprint/face; see [com.yawmiyati.app.ui.screens.auth.UnlockScreen]. */
    val biometricLoginEnabled: StateFlow<Boolean> = _biometricLoginEnabled

    /** Call with true only after a BiometricPrompt succeeded. */
    fun setBiometricLogin(enabled: Boolean) {
        tokenManager.setBiometricLoginEnabled(enabled)
        _biometricLoginEnabled.value = enabled
    }

    fun login(phone: String, password: String) {
        if (phone.isBlank() || password.isBlank()) {
            _uiState.value = AuthUiState.Error("يرجى إدخال رقم الهاتف وكلمة المرور")
            return
        }
        viewModelScope.launch {
            _uiState.value = AuthUiState.Loading
            _uiState.value = when (val result = repository.login(phone, password)) {
                is AuthResult.Success -> AuthUiState.Success(result.data)
                is AuthResult.Error -> AuthUiState.Error(result.message)
            }
        }
    }

    fun registerWorker(phone: String, password: String, fullName: String, consentVersion: Int) {
        if (phone.isBlank() || password.isBlank() || fullName.isBlank()) {
            _uiState.value = AuthUiState.Error("يرجى ملء جميع الحقول المطلوبة")
            return
        }
        viewModelScope.launch {
            _uiState.value = AuthUiState.Loading
            _uiState.value = when (val result = repository.registerWorker(
                phone, password, fullName, consentVersion)) {
                is AuthResult.Success -> AuthUiState.Success(result.data)
                is AuthResult.Error -> AuthUiState.Error(result.message)
            }
        }
    }

    fun registerBusiness(
        phone: String, password: String,
        legalName: String, contactName: String, contactPhone: String, consentVersion: Int
    ) {
        if (phone.isBlank() || password.isBlank() || legalName.isBlank() ||
            contactName.isBlank() || contactPhone.isBlank()
        ) {
            _uiState.value = AuthUiState.Error("يرجى ملء جميع الحقول المطلوبة")
            return
        }
        viewModelScope.launch {
            _uiState.value = AuthUiState.Loading
            _uiState.value = when (val result = repository.registerBusiness(
                phone, password, legalName, contactName, contactPhone, consentVersion
            )) {
                is AuthResult.Success -> AuthUiState.Success(result.data)
                is AuthResult.Error -> AuthUiState.Error(result.message)
            }
        }
    }

    /** Full logout: blacklists refresh token on server, wipes all local tokens. */
    fun logout() {
        viewModelScope.launch {
            repository.logout()
            _biometricLoginEnabled.value = false  // clear() wiped it with the session
            _uiState.value = AuthUiState.LoggedOut
        }
    }

    fun deleteAccount(password: String) {
        _deleteState.value = DeleteAccountState.Loading
        viewModelScope.launch {
            when (val result = repository.deleteAccount(password)) {
                is AuthResult.Success -> {
                    _uiState.value = AuthUiState.LoggedOut
                    _deleteState.value = DeleteAccountState.Success
                }
                is AuthResult.Error -> _deleteState.value = DeleteAccountState.Error(result.message)
            }
        }
    }

    fun resetDeleteState() {
        _deleteState.value = DeleteAccountState.Idle
    }

    fun resetState() {
        _uiState.value = AuthUiState.Idle
    }
}
