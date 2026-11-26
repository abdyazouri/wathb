package com.yawmiyati.app.ui.screens.worker

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.yawmiyati.app.data.api.AttendanceResponse
import com.yawmiyati.app.data.api.CompletionResponse
import com.yawmiyati.app.ui.utils.StatusLabels
import com.yawmiyati.app.ui.utils.formatArabicDate
import com.yawmiyati.app.viewmodels.WorkerAttendanceUiState
import com.yawmiyati.app.viewmodels.WorkerCompletionUiState

/**
 * «مهامي» → task details once the start time has come: check in, finish the job, and
 * confirm or dispute what the business recorded.
 */
@Composable
fun WorkerWorkSection(
    workerPhone: String,
    today: String,  // YYYY-MM-DD, Gaza time
    attendanceState: WorkerAttendanceUiState,
    completionState: WorkerCompletionUiState,
    isLoading: Boolean,
    onCheckIn: () -> Unit,
    onConfirmAttendance: (recordId: String) -> Unit,
    onDisputeAttendance: (recordId: String) -> Unit,
    onFinish: (hoursWorked: String?, notes: String) -> Unit,
    onConfirmCompletion: () -> Unit,
    onDisputeCompletion: () -> Unit,
) {
    var showFinishDialog by remember { mutableStateOf(false) }
    val records = (attendanceState as? WorkerAttendanceUiState.Success)?.records.orEmpty()
    val completion = (completionState as? WorkerCompletionUiState.Submitted)?.record
    fun mine(phone: String) = phone == workerPhone

    if (showFinishDialog) {
        FinishTaskDialog(
            onDismiss = { showFinishDialog = false },
            onConfirm = { hours, notes ->
                showFinishDialog = false
                onFinish(hours, notes)
            }
        )
    }

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("العمل جارٍ", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.primary)

        // ── Attendance ──
        Text("الحضور", style = MaterialTheme.typography.labelLarge)
        records.forEach { r -> AttendanceRow(r, mine(r.submittedByPhone), isLoading, onConfirmAttendance, onDisputeAttendance) }
        if (attendanceState is WorkerAttendanceUiState.Empty) {
            Text("لم يُسجَّل حضور بعد.", style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        val checkedInToday = records.any { it.workDate.take(10) == today }
        if (!checkedInToday && completion == null && attendanceState !is WorkerAttendanceUiState.Loading) {
            OutlinedButton(onClick = onCheckIn, enabled = !isLoading, modifier = Modifier.fillMaxWidth()) {
                Text("سجّل حضوري اليوم")
            }
        }

        HorizontalDivider()

        // ── Finishing the job ──
        Text("إنهاء المهمة", style = MaterialTheme.typography.labelLarge)
        when {
            completionState is WorkerCompletionUiState.Loading -> Unit
            completionState is WorkerCompletionUiState.Error ->
                Text(completionState.message, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            completion == null -> {
                Text("عند انتهاء الشغل اضغط «أنهيت المهمة». يؤكد صاحب العمل، وإن لم يرد خلال ٢٤ ساعة يتأكد تلقائيًا.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Button(onClick = { showFinishDialog = true }, enabled = !isLoading, modifier = Modifier.fillMaxWidth()) {
                    Text("أنهيت المهمة")
                }
            }
            else -> CompletionStatus(completion, mine(completion.submittedByPhone), isLoading, onConfirmCompletion, onDisputeCompletion)
        }
    }
}

@Composable
private fun AttendanceRow(
    record: AttendanceResponse,
    mine: Boolean,
    isLoading: Boolean,
    onConfirm: (String) -> Unit,
    onDispute: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            "${formatArabicDate(record.workDate)} — ${StatusLabels.attendance(record.status)}" +
                if (mine) "" else " (سجّله صاحب العمل)",
            style = MaterialTheme.typography.bodyMedium
        )
        if (!mine && record.status == "SUBMITTED") {
            ConfirmOrDispute(isLoading, onConfirm = { onConfirm(record.id) }, onDispute = { onDispute(record.id) })
        }
    }
}

@Composable
private fun CompletionStatus(
    record: CompletionResponse,
    mine: Boolean,
    isLoading: Boolean,
    onConfirm: () -> Unit,
    onDispute: () -> Unit,
) {
    when (record.status) {
        "SUBMITTED" -> if (mine) {
            Text("أرسلت «أنهيت المهمة». بانتظار تأكيد صاحب العمل، ويتأكد تلقائيًا بعد ٢٤ ساعة إن لم يرد.",
                style = MaterialTheme.typography.bodyMedium)
        } else {
            Text("سجّل صاحب العمل أن المهمة انتهت. هل هذا صحيح؟", style = MaterialTheme.typography.bodyMedium)
            ConfirmOrDispute(isLoading, onConfirm, onDispute)
        }
        "CONFIRMED" -> Text("✓ تم تأكيد إنهاء المهمة.", color = MaterialTheme.colorScheme.tertiary,
            style = MaterialTheme.typography.bodyMedium)
        "DISPUTED" -> Text("تم الاعتراض على إنهاء المهمة، وسيتابع المشرف.", color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodyMedium)
        else -> Text(StatusLabels.completion(record.status), style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun ConfirmOrDispute(isLoading: Boolean, onConfirm: () -> Unit, onDispute: () -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = onConfirm, enabled = !isLoading, modifier = Modifier.weight(1f)) { Text("أؤكد") }
        OutlinedButton(
            onClick = onDispute,
            enabled = !isLoading,
            colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
            modifier = Modifier.weight(1f)
        ) { Text("أعترض") }
    }
}

@Composable
private fun FinishTaskDialog(onDismiss: () -> Unit, onConfirm: (hoursWorked: String?, notes: String) -> Unit) {
    var hours by remember { mutableStateOf("") }
    var notes by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("أنهيت المهمة") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("سيُطلب من صاحب العمل تأكيد إنهاء المهمة، وبعدها يُسجَّل أجرك.")
                OutlinedTextField(
                    value = hours,
                    onValueChange = { v -> hours = v.filter { it.isDigit() || it == '.' }.take(5) },
                    label = { Text("ساعات العمل (اختياري)") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = notes,
                    onValueChange = { notes = it },
                    label = { Text("ملاحظات (اختياري)") },
                    minLines = 2,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            Button(onClick = { onConfirm(hours.ifBlank { null }, notes.trim()) }) { Text("تأكيد") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("إلغاء") } }
    )
}
