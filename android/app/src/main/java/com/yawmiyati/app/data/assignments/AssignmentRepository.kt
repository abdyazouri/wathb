package com.yawmiyati.app.data.assignments

import com.yawmiyati.app.data.api.ApiClient
import com.yawmiyati.app.data.api.ApiErrors
import com.yawmiyati.app.data.api.AssignmentResponse
import com.yawmiyati.app.data.api.AttendanceResponse
import com.yawmiyati.app.data.api.AttendanceSubmitRequest
import com.yawmiyati.app.data.api.CompletionResponse
import com.yawmiyati.app.data.api.CompletionSubmitRequest

sealed class AssignmentResult<out T> {
    data class Success<T>(val data: T) : AssignmentResult<T>()
    data class Error(val message: String, val isAuth: Boolean = false) : AssignmentResult<Nothing>()
}

open class AssignmentRepository {
    private val api = ApiClient.assignmentsApi

    open suspend fun listAssignments(): AssignmentResult<List<AssignmentResponse>> {
        return try {
            val response = api.listAssignments()
            if (response.isSuccessful) {
                AssignmentResult.Success(response.body()?.results ?: emptyList())
            } else {
                AssignmentResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
            }
        } catch (e: Exception) {
            AssignmentResult.Error(networkMessage(e))
        }
    }

    open suspend fun getAssignment(id: String): AssignmentResult<AssignmentResponse> {
        return try {
            val response = api.getAssignment(id)
            if (response.isSuccessful) AssignmentResult.Success(response.body()!!)
            else AssignmentResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { AssignmentResult.Error(networkMessage(e)) }
    }

    open suspend fun acceptAssignment(id: String): AssignmentResult<AssignmentResponse> {
        return try {
            val response = api.acceptAssignment(id)
            if (response.isSuccessful) {
                AssignmentResult.Success(response.body()!!)
            } else {
                val code = response.code()
                val msg = when (code) {
                    400 -> parseError(response.errorBody()?.string())
                    404 -> "المهمة غير موجودة"
                    else -> parseError(response.errorBody()?.string())
                }
                AssignmentResult.Error(msg, code == 401)
            }
        } catch (e: Exception) {
            AssignmentResult.Error(networkMessage(e))
        }
    }

    open suspend fun declineAssignment(id: String): AssignmentResult<AssignmentResponse> {
        return try {
            val response = api.declineAssignment(id)
            if (response.isSuccessful) {
                AssignmentResult.Success(response.body()!!)
            } else {
                val code = response.code()
                val msg = when (code) {
                    400 -> parseError(response.errorBody()?.string())
                    404 -> "المهمة غير موجودة"
                    else -> parseError(response.errorBody()?.string())
                }
                AssignmentResult.Error(msg, code == 401)
            }
        } catch (e: Exception) {
            AssignmentResult.Error(networkMessage(e))
        }
    }

    open suspend fun listAttendance(assignmentId: String): AssignmentResult<List<AttendanceResponse>> {
        return try {
            val response = api.listAttendance(assignmentId)
            if (response.isSuccessful) AssignmentResult.Success(response.body() ?: emptyList())
            else AssignmentResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { AssignmentResult.Error(networkMessage(e)) }
    }

    open suspend fun submitAttendance(assignmentId: String, request: AttendanceSubmitRequest): AssignmentResult<AttendanceResponse> {
        return try {
            val response = api.submitAttendance(assignmentId, request)
            if (response.isSuccessful) AssignmentResult.Success(response.body()!!)
            else AssignmentResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { AssignmentResult.Error(networkMessage(e)) }
    }

    open suspend fun confirmAttendance(assignmentId: String, recId: String): AssignmentResult<AttendanceResponse> {
        return try {
            val response = api.confirmAttendance(assignmentId, recId)
            if (response.isSuccessful) AssignmentResult.Success(response.body()!!)
            else AssignmentResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { AssignmentResult.Error(networkMessage(e)) }
    }

    open suspend fun disputeAttendance(assignmentId: String, recId: String): AssignmentResult<AttendanceResponse> {
        return try {
            val response = api.disputeAttendance(assignmentId, recId)
            if (response.isSuccessful) AssignmentResult.Success(response.body()!!)
            else AssignmentResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { AssignmentResult.Error(networkMessage(e)) }
    }

    open suspend fun getCompletion(assignmentId: String): AssignmentResult<CompletionResponse> {
        return try {
            val response = api.getCompletion(assignmentId)
            if (response.isSuccessful) AssignmentResult.Success(response.body()!!)
            else if (response.code() == 404) AssignmentResult.Error("لا يوجد سجل إتمام بعد", false)
            else AssignmentResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { AssignmentResult.Error(networkMessage(e)) }
    }

    open suspend fun submitCompletion(assignmentId: String, request: CompletionSubmitRequest): AssignmentResult<CompletionResponse> {
        return try {
            val response = api.submitCompletion(assignmentId, request)
            if (response.isSuccessful) AssignmentResult.Success(response.body()!!)
            else {
                val code = response.code()
                val msg = when (code) {
                    409 -> "تم تقديم سجل الإتمام مسبقاً"
                    else -> parseError(response.errorBody()?.string())
                }
                AssignmentResult.Error(msg, code == 401)
            }
        } catch (e: Exception) { AssignmentResult.Error(networkMessage(e)) }
    }

    open suspend fun confirmCompletion(assignmentId: String): AssignmentResult<CompletionResponse> {
        return try {
            val response = api.confirmCompletion(assignmentId)
            if (response.isSuccessful) AssignmentResult.Success(response.body()!!)
            else AssignmentResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { AssignmentResult.Error(networkMessage(e)) }
    }

    open suspend fun cancelAssignment(assignmentId: String, reason: String): AssignmentResult<AssignmentResponse> {
        return try {
            val resp = api.cancelAssignment(assignmentId, com.yawmiyati.app.data.api.CancelRequest(reason))
            if (resp.isSuccessful) AssignmentResult.Success(resp.body()!!)
            else AssignmentResult.Error(parseError(resp.errorBody()?.string()), resp.code() == 401)
        } catch (e: Exception) { AssignmentResult.Error(networkMessage(e)) }
    }

    open suspend fun disputeCompletion(
        assignmentId: String,
        request: com.yawmiyati.app.data.api.CompletionDisputeRequest = com.yawmiyati.app.data.api.CompletionDisputeRequest()
    ): AssignmentResult<CompletionResponse> {
        return try {
            val response = api.disputeCompletion(assignmentId, request)
            if (response.isSuccessful) AssignmentResult.Success(response.body()!!)
            else AssignmentResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { AssignmentResult.Error(networkMessage(e)) }
    }

    open suspend fun businessComplete(assignmentId: String): AssignmentResult<AssignmentResponse> {
        return try {
            val response = api.businessComplete(assignmentId)
            if (response.isSuccessful) AssignmentResult.Success(response.body()!!)
            else AssignmentResult.Error(parseError(response.errorBody()?.string()), response.code() == 401)
        } catch (e: Exception) { AssignmentResult.Error(networkMessage(e)) }
    }

    private fun parseError(body: String?): String = ApiErrors.message(body)

    private fun networkMessage(e: Exception): String = when {
        e is java.net.SocketTimeoutException -> "انتهت مهلة الاتصال بالخادم"
        e.message?.contains("Unable to resolve host") == true ||
            e.message?.contains("Failed to connect") == true -> "تعذّر الاتصال بالخادم"
        else -> e.localizedMessage ?: "خطأ في الشبكة"
    }
}
