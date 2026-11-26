package com.yawmiyati.app.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/** Worker: confirm «أتممت يوم عملي واطلب أجري». */
@Composable
fun RequestWageDialog(onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("أتممت يوم عملي واطلب أجري") },
        text = {
            Text("سيصل طلب أجرك إلى صاحب العمل الآن. إن لم يرد خلال ٢٤ ساعة يتأكد إتمام العمل تلقائيًا ويصبح أجرك مستحقًا.")
        },
        confirmButton = { Button(onClick = onConfirm) { Text("إرسال الطلب") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("إلغاء") } }
    )
}

/** «لم يتم العمل» reasons the server accepts. */
private val NOT_DONE_REASONS = listOf(
    "WORKER_NO_SHOW" to "العامل لم يحضر",
    "WORK_INCOMPLETE" to "العمل لم يكتمل",
)

/** Business: «لم يتم العمل» — a required reason, optional notes; opens a dispute for the admin. */
@Composable
fun NotDoneDialog(
    isLoading: Boolean,
    onConfirm: (category: String, notes: String) -> Unit,
    onDismiss: () -> Unit,
) {
    var category by remember { mutableStateOf<String?>(null) }
    var notes by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("لم يتم العمل") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("سيُفتح نزاع يتابعه مشرف وَثْب، ولن يُسجَّل أجر حتى يُحسم.", style = MaterialTheme.typography.bodyMedium)
                Text("السبب (مطلوب)", style = MaterialTheme.typography.labelLarge)
                NOT_DONE_REASONS.forEach { (value, label) ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(selected = category == value, onClick = { category = value })
                        Text(label)
                    }
                }
                OutlinedTextField(
                    value = notes,
                    onValueChange = { notes = it },
                    label = { Text("ملاحظات (اختياري)") },
                    supportingText = { Text("لا تكتب اسمًا أو رقم هاتف في الملاحظة") },
                    minLines = 2,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { category?.let { onConfirm(it, notes) } },
                enabled = category != null && !isLoading,
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
            ) { Text("إرسال") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("إلغاء") } }
    )
}
