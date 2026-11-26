package com.yawmiyati.app.viewmodels

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.yawmiyati.app.data.api.WageObligationResponse
import com.yawmiyati.app.data.auth.SessionEventBus
import com.yawmiyati.app.data.wages.WageRepository
import com.yawmiyati.app.data.wages.WageResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

sealed class WagesUiState {
    object Loading : WagesUiState()
    data class Success(val obligations: List<WageObligationResponse>) : WagesUiState()
    data class Error(val message: String) : WagesUiState()
    object Empty : WagesUiState()
}

sealed class WageActionState {
    object Idle : WageActionState()
    object Loading : WageActionState()
    object Success : WageActionState()
    data class Error(val message: String) : WageActionState()
}

class WagesViewModel(
    private val repository: WageRepository = WageRepository()
) : ViewModel() {

    private val _uiState = MutableStateFlow<WagesUiState>(WagesUiState.Loading)
    val uiState: StateFlow<WagesUiState> = _uiState

    private val _actionState = MutableStateFlow<WageActionState>(WageActionState.Idle)
    val actionState: StateFlow<WageActionState> = _actionState

    init { loadObligations() }

    fun loadObligations() {
        viewModelScope.launch {
            _uiState.value = WagesUiState.Loading
            when (val r = repository.listObligations()) {
                is WageResult.Success ->
                    _uiState.value = if (r.data.isEmpty()) WagesUiState.Empty
                                     else WagesUiState.Success(r.data)
                is WageResult.Error -> {
                    if (r.isAuth) SessionEventBus.emitSessionExpired()
                    else _uiState.value = WagesUiState.Error(r.message)
                }
            }
        }
    }


    fun resetActionState() {
        _actionState.value = WageActionState.Idle
    }
}
