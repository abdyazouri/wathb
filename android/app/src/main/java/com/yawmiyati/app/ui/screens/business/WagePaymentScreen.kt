package com.yawmiyati.app.ui.screens.business

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.yawmiyati.app.data.api.PaymentInfoResponse
import com.yawmiyati.app.ui.components.ErrorMessage
import com.yawmiyati.app.ui.components.LoadingIndicator
import com.yawmiyati.app.ui.components.PullableState
import com.yawmiyati.app.ui.components.Refreshable
import com.yawmiyati.app.ui.components.rememberSmsCodeConsent
import com.yawmiyati.app.ui.utils.StatusLabels
import com.yawmiyati.app.ui.utils.toArabic
import com.yawmiyati.app.ui.utils.toArabicAmountDisplay
import com.yawmiyati.app.ui.utils.toLocalPhone
import com.yawmiyati.app.viewmodels.WagePaymentState
import com.yawmiyati.app.viewmodels.WagePaymentViewModel
import kotlinx.coroutines.delay

/** «تحويل الأجر»: from the business's Jawwal Pay wallet straight to the worker's. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WagePaymentScreen(
    wageId: String,
    onBack: () -> Unit,
    onOpenProfile: () -> Unit,
    viewModel: WagePaymentViewModel = viewModel(),
) {
    val state by viewModel.state.collectAsState()
    LaunchedEffect(wageId) { viewModel.load(wageId) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("تحويل الأجر") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "رجوع") }
                }
            )
        }
    ) { padding ->
        Refreshable(isRefreshing = false, onRefresh = { viewModel.load(wageId) }, modifier = Modifier.padding(padding)) {
            val info = state.info
            when {
                state.loading -> PullableState { LoadingIndicator() }
                info == null -> PullableState {
                    ErrorMessage(message = state.error ?: "تعذّر التحميل", onRetry = { viewModel.load(wageId) })
                }
                else -> Column(
                    modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    PaymentSummary(info, showCopy = info.mode == "manual" && !state.paid)
                    when {
                        state.paid -> PaidSection(info, onBack)
                        !info.payable -> Text(
                            "حالة الأجر: ${StatusLabels.wageForBusiness(info.status)}",
                            style = MaterialTheme.typography.bodyLarge
                        )
                        info.mode == "manual" -> ManualSection(state, info, onDeclare = viewModel::declareManual)
                        state.needsWallet -> WalletNeededSection(onOpenProfile)
                        else -> AutomaticSection(
                            state = state,
                            onSend = viewModel::send,
                            onConfirm = viewModel::confirm,
                            onCheckStatus = { viewModel.load(wageId) },
                        )
                    }
                    state.error?.let {
                        Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }
    }
}

/** "8500" agorot → "85" / "85.50": what the business types in its Jawwal Pay app. */
private fun plainAmount(agorot: Long): String =
    if (agorot % 100 == 0L) (agorot / 100).toString() else "%d.%02d".format(agorot / 100, agorot % 100)

@Composable
private fun PaymentSummary(info: PaymentInfoResponse, showCopy: Boolean) {
    val clipboard = LocalClipboardManager.current
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(info.jobTitle, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            SummaryRow("العامل", info.workerName.ifBlank { "—" })
            SummaryRow(
                "محفظة العامل في Jawwal Pay", info.workerWallet.toLocalPhone(),
                onCopy = if (showCopy) ({ clipboard.setText(AnnotatedString(info.workerWallet.toLocalPhone())) }) else null
            )
            SummaryRow(
                "المبلغ المتفق عليه", info.amountDisplay.toArabicAmountDisplay(), emphasize = true,
                onCopy = if (showCopy) ({ clipboard.setText(AnnotatedString(plainAmount(info.amount))) }) else null
            )
        }
    }
}

@Composable
private fun SummaryRow(label: String, value: String, emphasize: Boolean = false, onCopy: (() -> Unit)? = null) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(modifier = Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                value,
                style = if (emphasize) MaterialTheme.typography.headlineSmall else MaterialTheme.typography.bodyLarge,
                color = if (emphasize) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface
            )
        }
        if (onCopy != null) {
            IconButton(onClick = onCopy) { Icon(Icons.Filled.ContentCopy, contentDescription = "نسخ $label") }
        }
    }
}

@Composable
private fun ManualSection(state: WagePaymentState, info: PaymentInfoResponse, onDeclare: (String) -> Unit) {
    var reference by remember { mutableStateOf("") }
    var confirming by remember { mutableStateOf(false) }
    if (confirming) {
        AlertDialog(
            onDismissRequest = { confirming = false },
            title = { Text("حوّلت الأجر؟") },
            text = { Text("هل حوّلت ${info.amountDisplay.toArabicAmountDisplay()} إلى محفظة العامل ${info.workerWallet.toLocalPhone()}؟ سيؤكد العامل الاستلام من جهته.") },
            confirmButton = { Button(onClick = { confirming = false; onDeclare(reference) }) { Text("نعم، حوّلت") } },
            dismissButton = { TextButton(onClick = { confirming = false }) { Text("إلغاء") } }
        )
    }
    Text("١. افتح تطبيق Jawwal Pay وحوّل المبلغ إلى محفظة العامل. استعمل زرّي النسخ.", style = MaterialTheme.typography.bodyMedium)
    Text("٢. ارجع إلى وَثْب، اكتب رقم العملية واضغط «حوّلت الأجر».", style = MaterialTheme.typography.bodyMedium)
    OutlinedTextField(
        value = reference,
        onValueChange = { reference = it.take(100) },
        label = { Text("رقم العملية في Jawwal Pay") },
        supportingText = { Text("مطلوب: تجده في رسالة Jawwal Pay أو في سجل العمليات.") },
        singleLine = true,
        modifier = Modifier.fillMaxWidth()
    )
    // The server refuses a declaration without the Jawwal Pay transaction number.
    Button(onClick = { confirming = true }, enabled = !state.busy && reference.isNotBlank(), modifier = Modifier.fillMaxWidth()) {
        if (state.busy) CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.padding(end = 8.dp))
        Text("حوّلت الأجر")
    }
}

@Composable
private fun WalletNeededSection(onOpenProfile: () -> Unit) {
    Text("لتحويل الأجر من وَثْب اربط محفظة Jawwal Pay في ملف المنشأة أولًا.", style = MaterialTheme.typography.bodyLarge)
    Button(onClick = onOpenProfile, modifier = Modifier.fillMaxWidth()) { Text("ربط المحفظة") }
}

@Composable
private fun AutomaticSection(
    state: WagePaymentState,
    onSend: () -> Unit,
    onConfirm: (String) -> Unit,
    onCheckStatus: () -> Unit,
) {
    // Not rememberSaveable: the code must not be written to saved instance state.
    var code by remember { mutableStateOf("") }
    val startSmsConsent = rememberSmsCodeConsent { code = it }
    val now by produceState(System.currentTimeMillis(), state.resendAtMillis) {
        while (true) {
            value = System.currentTimeMillis()
            delay(1_000)
        }
    }
    val sendAndListen = { startSmsConsent(); onSend() }

    state.info?.businessWallet?.let {
        Text("من محفظتك: ${it.toLocalPhone()}", style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    when {
        state.timeout -> {
            Text("لم يصل رد من Jawwal Pay. لن نرسل تحويلًا جديدًا قبل أن نعرف ما حدث للسابق.",
                style = MaterialTheme.typography.bodyMedium)
            OutlinedButton(onClick = onCheckStatus, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) {
                Text("تحقق من حالة التحويل")
            }
        }
        !state.codeSent -> {
            Text("سيصلك رمز في رسالة من Jawwal Pay لتأكيد التحويل.", style = MaterialTheme.typography.bodyMedium)
            Button(onClick = sendAndListen, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) {
                if (state.busy) CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.padding(end = 8.dp))
                Text("إرسال")
            }
        }
        else -> {
            OutlinedTextField(
                value = code,
                onValueChange = { v -> code = v.filter { it.isDigit() }.take(8) },
                label = { Text("رمز التأكيد") },
                supportingText = { Text("يُملأ تلقائيًا عند وصول الرسالة إن وافقت، أو اكتبه بنفسك.") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                modifier = Modifier.fillMaxWidth()
            )
            Button(onClick = { onConfirm(code) }, enabled = !state.busy && code.length >= 4, modifier = Modifier.fillMaxWidth()) {
                if (state.busy) CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.padding(end = 8.dp))
                Text("تأكيد التحويل")
            }
            val waitSeconds = state.resendAtMillis?.let { ((it - now) / 1000).coerceAtLeast(0) } ?: 0
            TextButton(onClick = sendAndListen, enabled = !state.busy && waitSeconds == 0L) {
                Text(if (waitSeconds > 0) "إعادة إرسال الرمز بعد ${waitSeconds.toInt().toArabic()} ثانية" else "إعادة إرسال الرمز")
            }
        }
    }
}

@Composable
private fun PaidSection(info: PaymentInfoResponse, onBack: () -> Unit) {
    val automatic = info.mode == "automatic"
    Text(
        if (automatic) "✓ تم تحويل الأجر إلى محفظة العامل." else "✓ سجّلنا أنك حوّلت الأجر.",
        style = MaterialTheme.typography.titleMedium,
        color = MaterialTheme.colorScheme.tertiary
    )
    Text(
        if (automatic) "أبلغنا العامل. إن لم يصله الأجر يمكنه الاعتراض خلال ٢٤ ساعة."
        else "سيؤكد العامل الاستلام من جهته.",
        style = MaterialTheme.typography.bodyMedium
    )
    Button(onClick = onBack, modifier = Modifier.fillMaxWidth()) { Text("رجوع") }
}
