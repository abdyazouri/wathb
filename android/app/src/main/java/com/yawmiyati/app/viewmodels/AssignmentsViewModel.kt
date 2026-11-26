package com.yawmiyati.app.viewmodels

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.yawmiyati.app.data.api.AssignmentResponse
import com.yawmiyati.app.data.assignments.AssignmentRepository
import com.yawmiyati.app.data.assignments.AssignmentResult
import com.yawmiyati.app.data.wages.WageRepository
import com.yawmiyati.app.data.wages.WageResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

sealed class AssignmentsUiState {
    object Loading : AssignmentsUiState()
    data class Success(val assignments: List<AssignmentResponse>) : AssignmentsUiState()
    data class Error(val message: String) : AssignmentsUiState()
    object Empty : AssignmentsUiState()
}

sealed class AssignmentActionState {
    object Idle : AssignmentActionState()
    object Loading : AssignmentActionState()
    object Success : AssignmentActionState()
    data class Error(val message: String) : AssignmentActionState()
}

class AssignmentsViewModel(
    private val repository: AssignmentRepository = AssignmentRepository(),
    private val wageRepository: WageRepository = WageRepository()
) : ViewModel() {

    private val _uiState = MutableStateFlow<AssignmentsUiState>(AssignmentsUiState.Loading)
    val uiState: StateFlow<AssignmentsUiState> = _uiState

    private val _actionState = MutableStateFlow<AssignmentActionState>(AssignmentActionState.Idle)
    val actionState: StateFlow<AssignmentActionState> = _actionState

    init { loadAssignments() }

    fun loadAssignments() {
        viewModelScope.launch {
            _uiState.value = AssignmentsUiState.Loading
            _uiState.value = when (val result = repository.listAssignments()) {
                is AssignmentResult.Success ->
                    if (result.data.isEmpty()) AssignmentsUiState.Empty
                    else AssignmentsUiState.Success(result.data)
                is AssignmentResult.Error -> AssignmentsUiState.Error(result.message)
            }
        }
    }

    fun acceptAssignment(id: String) = performActionAndUpdate(id, accept = true)
    fun declineAssignment(id: String) = performActionAndUpdate(id, accept = false)

    private fun performActionAndUpdate(id: String, accept: Boolean) {
        if (_actionState.value is AssignmentActionState.Loading) return
        viewModelScope.launch {
            _actionState.value = AssignmentActionState.Loading
            val result = if (accept) repository.acceptAssignment(id) else repository.declineAssignment(id)
            when (result) {
                is AssignmentResult.Success -> {
                    _actionState.value = AssignmentActionState.Success
                    val current = _uiState.value
                    if (current is AssignmentsUiState.Success) {
                        val updated = current.assignments.map {
                            if (it.id == result.data.id) result.data else it
                        }
                        _uiState.value = AssignmentsUiState.Success(updated)
                    }
                }
                is AssignmentResult.Error -> {
                    _actionState.value = AssignmentActionState.Error(result.message)
                }
            }
        }
    }

    /** Worker: «أتممت يوم عملي واطلب أجري». The server ignores a second press. */
    fun requestWage(id: String) = performAndReload {
        repository.submitCompletion(id, com.yawmiyati.app.data.api.CompletionSubmitRequest())
    }

    /** Business: «لم يتم العمل» with [category] WORKER_NO_SHOW or WORK_INCOMPLETE. */
    fun reportNotDone(id: String, category: String, description: String) = performAndReload {
        repository.disputeCompletion(id, com.yawmiyati.app.data.api.CompletionDisputeRequest(category, description.trim()))
    }

    private fun performAndReload(block: suspend () -> AssignmentResult<*>) {
        if (_actionState.value is AssignmentActionState.Loading) return
        viewModelScope.launch {
            _actionState.value = AssignmentActionState.Loading
            _actionState.value = when (val result = block()) {
                is AssignmentResult.Success -> {
                    loadAssignments()
                    AssignmentActionState.Success
                }
                is AssignmentResult.Error -> AssignmentActionState.Error(result.message)
            }
        }
    }

    private val _paymentToOpen = MutableStateFlow<String?>(null)
    /** Wage to pay right after «تأكيد ودفع الأجر» confirmed the work. */
    val paymentToOpen: StateFlow<String?> = _paymentToOpen
    fun paymentOpened() { _paymentToOpen.value = null }

    fun businessComplete(id: String) {
        if (_actionState.value is AssignmentActionState.Loading) return
        viewModelScope.launch {
            _actionState.value = AssignmentActionState.Loading
            when (val result = repository.businessComplete(id)) {
                is AssignmentResult.Success -> {
                    _actionState.value = AssignmentActionState.Success
                    _paymentToOpen.value = result.data.wageObligationId
                    val current = _uiState.value
                    if (current is AssignmentsUiState.Success) {
                        val updated = current.assignments.map {
                            if (it.id == result.data.id) result.data else it
                        }
                        _uiState.value = AssignmentsUiState.Success(updated)
                    }
                }
                is AssignmentResult.Error -> {
                    _actionState.value = AssignmentActionState.Error(result.message)
                }
            }
        }
    }

    /** Call only after the worker passed BiometricPrompt, or with their [password]. */
    fun acknowledgeWage(obligationId: String, password: String? = null) {
        if (_actionState.value is AssignmentActionState.Loading) return
        viewModelScope.launch {
            _actionState.value = AssignmentActionState.Loading
            when (val result = wageRepository.acknowledgePayment(obligationId, password)) {
                is WageResult.Success -> {
                    _actionState.value = AssignmentActionState.Success
                    loadAssignments()
                }
                is WageResult.Error -> {
                    _actionState.value = AssignmentActionState.Error(result.message)
                }
            }
        }
    }

    fun disputeWage(obligationId: String, description: String) {
        if (_actionState.value is AssignmentActionState.Loading) return
        viewModelScope.launch {
            _actionState.value = AssignmentActionState.Loading
            when (val result = wageRepository.disputePayment(obligationId, description)) {
                is WageResult.Success -> {
                    _actionState.value = AssignmentActionState.Success
                    loadAssignments()
                }
                is WageResult.Error -> {
                    _actionState.value = AssignmentActionState.Error(result.message)
                }
            }
        }
    }

    fun resetActionState() {
        _actionState.value = AssignmentActionState.Idle
    }
}
