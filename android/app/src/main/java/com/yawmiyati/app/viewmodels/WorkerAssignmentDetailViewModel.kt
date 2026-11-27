package com.yawmiyati.app.viewmodels

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.yawmiyati.app.data.api.AssignmentResponse
import com.yawmiyati.app.data.api.AttendanceResponse
import com.yawmiyati.app.data.api.AttendanceSubmitRequest
import com.yawmiyati.app.data.api.CompletionResponse
import com.yawmiyati.app.data.api.CompletionSubmitRequest
import com.yawmiyati.app.data.api.WageObligationResponse
import com.yawmiyati.app.data.assignments.AssignmentRepository
import com.yawmiyati.app.data.assignments.AssignmentResult
import com.yawmiyati.app.data.wages.WageRepository
import com.yawmiyati.app.data.wages.WageResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

sealed class WorkerAttendanceUiState {
    object Loading : WorkerAttendanceUiState()
    object Empty : WorkerAttendanceUiState()
    data class Success(val records: List<AttendanceResponse>) : WorkerAttendanceUiState()
    data class Error(val message: String) : WorkerAttendanceUiState()
}

sealed class WorkerCompletionUiState {
    object Loading : WorkerCompletionUiState()
    object NotSubmitted : WorkerCompletionUiState()
    data class Submitted(val record: CompletionResponse) : WorkerCompletionUiState()
    data class Error(val message: String) : WorkerCompletionUiState()
}

sealed class WorkerAssignmentActionState {
    object Idle : WorkerAssignmentActionState()
    object Loading : WorkerAssignmentActionState()
    object Success : WorkerAssignmentActionState()
    data class Error(val message: String) : WorkerAssignmentActionState()
}

class WorkerAssignmentDetailViewModel(
    private val repository: AssignmentRepository = AssignmentRepository(),
    private val wageRepository: WageRepository = WageRepository()
) : ViewModel() {

    private val _attendanceState = MutableStateFlow<WorkerAttendanceUiState>(WorkerAttendanceUiState.Loading)
    val attendanceState: StateFlow<WorkerAttendanceUiState> = _attendanceState

    private val _completionState = MutableStateFlow<WorkerCompletionUiState>(WorkerCompletionUiState.Loading)
    val completionState: StateFlow<WorkerCompletionUiState> = _completionState

    private val _actionState = MutableStateFlow<WorkerAssignmentActionState>(WorkerAssignmentActionState.Idle)
    val actionState: StateFlow<WorkerAssignmentActionState> = _actionState

    /** The assignment as the server has it now (status, work date and start time). */
    private val _assignment = MutableStateFlow<AssignmentResponse?>(null)
    val assignment: StateFlow<AssignmentResponse?> = _assignment

    private val _wagesForAssignment = MutableStateFlow<WageObligationResponse?>(null)
    val wagesForAssignment: StateFlow<WageObligationResponse?> = _wagesForAssignment

    private var currentAssignmentId: String? = null

    /** Pull-to-refresh: reload everything even for the same assignment. */
    fun refresh(assignmentId: String) {
        currentAssignmentId = null
        load(assignmentId)
    }

    fun load(assignmentId: String) {
        if (currentAssignmentId == assignmentId) return
        currentAssignmentId = assignmentId
        loadAssignment(assignmentId)
        loadAttendance(assignmentId)
        loadCompletion(assignmentId)
        loadWagesForAssignment(assignmentId)
    }

    private fun loadAssignment(assignmentId: String) {
        viewModelScope.launch {
            val r = repository.getAssignment(assignmentId)
            if (r is AssignmentResult.Success) _assignment.value = r.data
        }
    }

    private fun loadWagesForAssignment(assignmentId: String) {
        viewModelScope.launch {
            when (val r = wageRepository.listObligations()) {
                is WageResult.Success -> {
                    _wagesForAssignment.value = r.data.firstOrNull { it.assignment == assignmentId }
                }
                is WageResult.Error -> { /* ignore — wage might not exist yet */ }
            }
        }
    }

    /** Call only after the worker passed BiometricPrompt, or with their [password]. */
    fun acknowledgeWage(obligationId: String, password: String? = null) = performAction {
        when (val r = wageRepository.acknowledgePayment(obligationId, password)) {
            is WageResult.Success -> {
                _wagesForAssignment.value = r.data
                AssignmentResult.Success(Unit)
            }
            is WageResult.Error -> AssignmentResult.Error(r.message)
        }
    }

    fun disputeWage(obligationId: String, reason: String) = performAction {
        when (val r = wageRepository.disputePayment(obligationId, reason)) {
            is WageResult.Success -> {
                _wagesForAssignment.value = r.data
                AssignmentResult.Success(Unit)
            }
            is WageResult.Error -> AssignmentResult.Error(r.message)
        }
    }

    private fun loadAttendance(assignmentId: String) {
        viewModelScope.launch {
            _attendanceState.value = WorkerAttendanceUiState.Loading
            when (val r = repository.listAttendance(assignmentId)) {
                is AssignmentResult.Success ->
                    _attendanceState.value = if (r.data.isEmpty()) WorkerAttendanceUiState.Empty
                                             else WorkerAttendanceUiState.Success(r.data)
                is AssignmentResult.Error ->
                    _attendanceState.value = WorkerAttendanceUiState.Error(r.message)
            }
        }
    }

    private fun loadCompletion(assignmentId: String) {
        viewModelScope.launch {
            _completionState.value = WorkerCompletionUiState.Loading
            when (val r = repository.getCompletion(assignmentId)) {
                is AssignmentResult.Success ->
                    _completionState.value = WorkerCompletionUiState.Submitted(r.data)
                is AssignmentResult.Error ->
                    _completionState.value = if (r.notFound)
                        WorkerCompletionUiState.NotSubmitted
                    else WorkerCompletionUiState.Error(r.message)
            }
        }
    }

    fun submitAttendance(assignmentId: String, workDate: String, notes: String) {
        if (_actionState.value is WorkerAssignmentActionState.Loading) return
        viewModelScope.launch {
            _actionState.value = WorkerAssignmentActionState.Loading
            val req = AttendanceSubmitRequest(workDate = workDate, notes = notes)
            when (val r = repository.submitAttendance(assignmentId, req)) {
                is AssignmentResult.Success -> {
                    _actionState.value = WorkerAssignmentActionState.Success
                    loadAttendance(assignmentId)
                }
                is AssignmentResult.Error -> _actionState.value = WorkerAssignmentActionState.Error(r.message)
            }
        }
    }

    fun submitCompletion(assignmentId: String, hoursWorked: String?, notes: String) {
        if (_actionState.value is WorkerAssignmentActionState.Loading) return
        viewModelScope.launch {
            _actionState.value = WorkerAssignmentActionState.Loading
            val req = CompletionSubmitRequest(
                hoursWorked = hoursWorked?.takeIf { it.isNotBlank() },
                notes = notes
            )
            when (val r = repository.submitCompletion(assignmentId, req)) {
                is AssignmentResult.Success -> {
                    _actionState.value = WorkerAssignmentActionState.Success
                    _completionState.value = WorkerCompletionUiState.Submitted(r.data)
                    loadAssignment(assignmentId)  // now ACTIVE
                }
                is AssignmentResult.Error -> _actionState.value = WorkerAssignmentActionState.Error(r.message)
            }
        }
    }

    fun confirmAttendance(assignmentId: String, recId: String) = performAction {
        repository.confirmAttendance(assignmentId, recId).also { result ->
            if (result is AssignmentResult.Success) {
                updateAttendanceRecord(result.data)
            }
        }
    }

    fun disputeAttendance(assignmentId: String, recId: String) = performAction {
        repository.disputeAttendance(assignmentId, recId).also { result ->
            if (result is AssignmentResult.Success) {
                updateAttendanceRecord(result.data)
            }
        }
    }

    fun confirmCompletion(assignmentId: String) = performAction {
        repository.confirmCompletion(assignmentId).also { result ->
            if (result is AssignmentResult.Success) {
                _completionState.value = WorkerCompletionUiState.Submitted(result.data)
                // COMPLETED: the wage now exists.
                loadAssignment(assignmentId)
                loadWagesForAssignment(assignmentId)
            }
        }
    }

    fun disputeCompletion(assignmentId: String) = performAction {
        repository.disputeCompletion(assignmentId).also { result ->
            if (result is AssignmentResult.Success) {
                _completionState.value = WorkerCompletionUiState.Submitted(result.data)
            }
        }
    }

    private fun performAction(block: suspend () -> AssignmentResult<*>) {
        if (_actionState.value is WorkerAssignmentActionState.Loading) return
        viewModelScope.launch {
            _actionState.value = WorkerAssignmentActionState.Loading
            val result = block()
            _actionState.value = when (result) {
                is AssignmentResult.Success -> WorkerAssignmentActionState.Success
                is AssignmentResult.Error   -> WorkerAssignmentActionState.Error(result.message)
            }
        }
    }

    private fun updateAttendanceRecord(updated: AttendanceResponse) {
        val current = _attendanceState.value
        if (current is WorkerAttendanceUiState.Success) {
            _attendanceState.value = WorkerAttendanceUiState.Success(
                current.records.map { if (it.id == updated.id) updated else it }
            )
        }
    }

    fun cancelAssignment(assignmentId: String, reason: String) =
        performAction {
            repository.cancelAssignment(assignmentId, reason).also { result ->
                if (result is AssignmentResult.Success) _assignment.value = result.data
            }
        }

    fun resetActionState() {
        _actionState.value = WorkerAssignmentActionState.Idle
    }
}
