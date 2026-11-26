package com.yawmiyati.app.ui.components

import android.content.Context
import android.content.ContextWrapper
import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.fragment.app.FragmentActivity
import com.yawmiyati.app.data.auth.BiometricHelper

/** How the worker proves it is them before "استلمت". Disputing needs neither. */
enum class AcknowledgeAuth { DEVICE_PROMPT, ACCOUNT_PASSWORD }

/** BiometricPrompt (fingerprint or screen lock) when the phone has one; otherwise the account password. */
fun acknowledgeAuthFor(deviceAuthAvailable: Boolean): AcknowledgeAuth =
    if (deviceAuthAvailable) AcknowledgeAuth.DEVICE_PROMPT else AcknowledgeAuth.ACCOUNT_PASSWORD

/**
 * Returns the function to call when the worker taps "استلمت". It never acknowledges directly:
 * [onAcknowledge] runs only after BiometricPrompt succeeds (password = null) or after the worker
 * types the account password, which the server then checks (403 if wrong).
 */
@Composable
fun rememberWageAcknowledgeGate(
    onAcknowledge: (obligationId: String, password: String?) -> Unit
): (obligationId: String) -> Unit {
    val context = LocalContext.current
    val currentOnAcknowledge by rememberUpdatedState(onAcknowledge)
    var passwordFor by rememberSaveable { mutableStateOf<String?>(null) }

    passwordFor?.let { obligationId ->
        AcknowledgePasswordDialog(
            onDismiss = { passwordFor = null },
            onConfirm = { password ->
                passwordFor = null
                currentOnAcknowledge(obligationId, password)
            }
        )
    }

    return remember(context) {
        { obligationId ->
            val activity = context.findFragmentActivity()
            val deviceAuth = activity != null && BiometricHelper.isAvailable(context)
            when (acknowledgeAuthFor(deviceAuth)) {
                AcknowledgeAuth.DEVICE_PROMPT -> BiometricHelper.prompt(
                    activity = activity!!,
                    title = "تأكيد استلام الأجر",
                    subtitle = "استخدم بصمتك أو قفل الشاشة",
                    onSuccess = { currentOnAcknowledge(obligationId, null) },
                    onError = { message -> Toast.makeText(context, message, Toast.LENGTH_LONG).show() }
                )
                AcknowledgeAuth.ACCOUNT_PASSWORD -> passwordFor = obligationId
            }
        }
    }
}

@Composable
private fun AcknowledgePasswordDialog(
    onDismiss: () -> Unit,
    onConfirm: (password: String) -> Unit
) {
    // Not rememberSaveable: the password must not be written to saved instance state.
    var password by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("تأكيد استلام الأجر") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("لا توجد بصمة ولا قفل شاشة على هذا الهاتف. أدخل كلمة مرور حسابك لتأكيد أنك استلمت الأجر.")
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    label = { Text("كلمة المرور") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            Button(onClick = { onConfirm(password) }, enabled = password.isNotBlank()) { Text("تأكيد") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("إلغاء") }
        }
    )
}

internal tailrec fun Context.findFragmentActivity(): FragmentActivity? = when (this) {
    is FragmentActivity -> this
    is ContextWrapper -> baseContext.findFragmentActivity()
    else -> null
}
