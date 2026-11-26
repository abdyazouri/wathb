package com.yawmiyati.app.ui.components

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import com.google.android.gms.auth.api.phone.SmsRetriever
import com.google.android.gms.common.api.CommonStatusCodes
import com.google.android.gms.common.api.Status

/** The first standalone run of 4–8 digits in an SMS, e.g. the Jawwal Pay confirmation code. */
fun extractSmsCode(message: String?): String? =
    message?.let { Regex("(?<!\\d)\\d{4,8}(?!\\d)").find(it)?.value }

/**
 * SMS User Consent API: when the next SMS with a code arrives, Android asks the user once
 * whether Wathb may read *that one message*. No READ_SMS permission. Returns the function
 * that starts listening (call it right after asking Jawwal Pay to send the code).
 * The code goes only into the code field; it is never logged or stored.
 */
@Composable
fun rememberSmsCodeConsent(onCode: (String) -> Unit): () -> Unit {
    val context = LocalContext.current
    val currentOnCode by rememberUpdatedState(onCode)
    val consentLauncher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            extractSmsCode(result.data?.getStringExtra(SmsRetriever.EXTRA_SMS_MESSAGE))?.let(currentOnCode)
        }
    }

    DisposableEffect(context) {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context, intent: Intent) {
                if (intent.action != SmsRetriever.SMS_RETRIEVED_ACTION) return
                val extras = intent.extras ?: return
                @Suppress("DEPRECATION")
                val status = extras.get(SmsRetriever.EXTRA_STATUS) as? Status ?: return
                if (status.statusCode != CommonStatusCodes.SUCCESS) return  // e.g. 5-minute timeout
                @Suppress("DEPRECATION")
                val consent = extras.getParcelable<Intent>(SmsRetriever.EXTRA_CONSENT_INTENT) ?: return
                // Only launch Google Play services' own consent screen, without URI grants.
                val target = consent.resolveActivity(c.packageManager) ?: return
                val grants = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                if (target.packageName != "com.google.android.gms" || consent.flags and grants != 0) return
                runCatching { consentLauncher.launch(consent) }
            }
        }
        ContextCompat.registerReceiver(
            context, receiver, IntentFilter(SmsRetriever.SMS_RETRIEVED_ACTION),
            SmsRetriever.SEND_PERMISSION, null, ContextCompat.RECEIVER_EXPORTED
        )
        onDispose { context.unregisterReceiver(receiver) }
    }

    return remember(context) { { SmsRetriever.getClient(context).startSmsUserConsent(null); Unit } }
}
