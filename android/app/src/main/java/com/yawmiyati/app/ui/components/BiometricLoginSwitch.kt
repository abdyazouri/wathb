package com.yawmiyati.app.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import com.yawmiyati.app.data.auth.BiometricHelper
import com.yawmiyati.app.viewmodels.AuthViewModel

/** Profile setting: open the app with fingerprint/face. Turning it on needs one successful prompt. */
@Composable
fun BiometricLoginSwitch(authViewModel: AuthViewModel, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val enabled by authViewModel.biometricLoginEnabled.collectAsState()
    val available = BiometricHelper.isAvailable(context)
    if (!available && !enabled) return  // nothing to offer on this phone

    Row(modifier = modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(modifier = Modifier.weight(1f)) {
            Text("الدخول بالبصمة أو الوجه", style = MaterialTheme.typography.bodyLarge)
            Text(
                "عند فتح التطبيق بدل كلمة المرور",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        Switch(
            checked = enabled,
            onCheckedChange = { turnOn ->
                val activity = context.findFragmentActivity()
                if (!turnOn) {
                    authViewModel.setBiometricLogin(false)
                } else if (activity != null && available) {
                    BiometricHelper.prompt(
                        activity = activity,
                        title = "تفعيل الدخول بالبصمة",
                        subtitle = "أكّد ببصمتك أو وجهك أو قفل الشاشة",
                        onSuccess = { authViewModel.setBiometricLogin(true) },
                        onError = {}
                    )
                }
            }
        )
    }
}
