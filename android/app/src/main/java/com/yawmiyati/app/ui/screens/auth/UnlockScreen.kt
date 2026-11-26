package com.yawmiyati.app.ui.screens.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Fingerprint
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.yawmiyati.app.data.auth.BiometricHelper
import com.yawmiyati.app.ui.components.findFragmentActivity
import com.yawmiyati.app.ui.theme.WathbDeepTeal

/**
 * Shown on app start when the user enabled fingerprint/face login. The saved session is
 * used only after BiometricPrompt succeeds; there is no other way past this screen except
 * signing in again with the password.
 */
@Composable
fun UnlockScreen(
    onUnlocked: () -> Unit,
    onUsePassword: () -> Unit,
) {
    val context = LocalContext.current
    val activity = remember(context) { context.findFragmentActivity() }
    val available = activity != null && BiometricHelper.isAvailable(context)
    var error by remember { mutableStateOf<String?>(null) }

    val prompt = {
        if (activity != null && BiometricHelper.isAvailable(context)) {
            error = null
            BiometricHelper.prompt(
                activity = activity,
                title = "الدخول إلى وَثْب",
                subtitle = "استخدم بصمتك أو وجهك أو قفل الشاشة",
                onSuccess = onUnlocked,
                onError = { error = it }
            )
        }
    }
    LaunchedEffect(Unit) { prompt() }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text("وَثْب", style = MaterialTheme.typography.displaySmall, color = WathbDeepTeal)
        Spacer(Modifier.height(24.dp))
        if (available) {
            Icon(Icons.Filled.Fingerprint, contentDescription = null, tint = WathbDeepTeal, modifier = Modifier.size(72.dp))
            Spacer(Modifier.height(16.dp))
            Text("افتح التطبيق ببصمتك أو وجهك", style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
            error?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center)
            }
            Spacer(Modifier.height(24.dp))
            Button(
                onClick = prompt,
                colors = ButtonDefaults.buttonColors(containerColor = WathbDeepTeal),
                modifier = Modifier.fillMaxWidth().height(52.dp)
            ) { Text("الدخول بالبصمة") }
        } else {
            Text(
                "لا توجد بصمة ولا قفل شاشة على الهاتف الآن، فادخل بكلمة المرور.",
                style = MaterialTheme.typography.bodyLarge,
                textAlign = TextAlign.Center
            )
        }
        Spacer(Modifier.height(12.dp))
        TextButton(onClick = onUsePassword) { Text("الدخول بكلمة المرور") }
    }
}
