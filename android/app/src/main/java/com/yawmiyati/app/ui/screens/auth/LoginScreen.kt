package com.yawmiyati.app.ui.screens.auth

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.yawmiyati.app.ui.theme.WathbDeepTeal
import com.yawmiyati.app.ui.theme.WathbGold
import com.yawmiyati.app.ui.theme.WathbTeal
import com.yawmiyati.app.viewmodels.AuthUiState
import com.yawmiyati.app.viewmodels.AuthViewModel
import com.yawmiyati.app.ui.components.findFragmentActivity
import com.yawmiyati.app.data.auth.BiometricHelper
import androidx.compose.ui.platform.LocalContext
import androidx.compose.material3.AlertDialog

@Composable
fun LoginScreen(
    onLoginSuccess: (role: String) -> Unit,
    onNavigateToRegister: () -> Unit,
    viewModel: AuthViewModel = viewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    var phone    by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }

    val context = LocalContext.current
    // After a password login: offer fingerprint/face for next time (once per login).
    var offerBiometricFor by remember { mutableStateOf<String?>(null) }
    offerBiometricFor?.let { role ->
        val finish = { offerBiometricFor = null; onLoginSuccess(role) }
        AlertDialog(
            onDismissRequest = finish,
            title = { Text("الدخول بالبصمة") },
            text = { Text("هل تريد فتح التطبيق ببصمتك أو وجهك في المرات القادمة بدل كلمة المرور؟") },
            confirmButton = {
                Button(onClick = {
                    val activity = context.findFragmentActivity()
                    if (activity == null) finish() else BiometricHelper.prompt(
                        activity = activity,
                        title = "تفعيل الدخول بالبصمة",
                        subtitle = "أكّد ببصمتك أو وجهك أو قفل الشاشة",
                        onSuccess = { viewModel.setBiometricLogin(true); finish() },
                        onError = { finish() }
                    )
                }) { Text("تفعيل") }
            },
            dismissButton = { TextButton(onClick = finish) { Text("ليس الآن") } }
        )
    }

    LaunchedEffect(uiState) {
        when (val state = uiState) {
            is AuthUiState.Success -> {
                viewModel.resetState()
                if (BiometricHelper.isAvailable(context) && !viewModel.biometricLoginEnabled.value) {
                    offerBiometricFor = state.user.role
                } else {
                    onLoginSuccess(state.user.role)
                }
            }
            is AuthUiState.Error   -> { snackbarHostState.showSnackbar(state.message); viewModel.resetState() }
            else -> {}
        }
    }

    Scaffold(snackbarHost = { SnackbarHost(snackbarHostState) }) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .imePadding()
                .verticalScroll(rememberScrollState())
        ) {
            // ── Brand hero ─────────────────────────────────────────────────────
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(260.dp)
                    .background(WathbDeepTeal),
                contentAlignment = Alignment.Center
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        text = "وَثْب",
                        style = MaterialTheme.typography.displayLarge.copy(fontSize = 56.sp),
                        color = WathbGold,
                        textAlign = TextAlign.Center
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = "خطوتك للشغل الجاي",
                        style = MaterialTheme.typography.bodyLarge,
                        color = Color.White.copy(alpha = 0.85f),
                        textAlign = TextAlign.Center
                    )
                }
            }

            // ── Form card ──────────────────────────────────────────────────────
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 24.dp, vertical = 32.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(
                    text = "تسجيل الدخول",
                    style = MaterialTheme.typography.titleLarge,
                    color = WathbDeepTeal
                )

                Spacer(Modifier.height(24.dp))

                OutlinedTextField(
                    value = phone,
                    onValueChange = { phone = it },
                    label = { Text("رقم الهاتف") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Phone,
                        imeAction = ImeAction.Next
                    ),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = WathbDeepTeal,
                        focusedLabelColor  = WathbDeepTeal,
                        cursorColor        = WathbDeepTeal
                    ),
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(Modifier.height(16.dp))

                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    label = { Text("كلمة المرور") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Password,
                        imeAction = ImeAction.Done
                    ),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = WathbDeepTeal,
                        focusedLabelColor  = WathbDeepTeal,
                        cursorColor        = WathbDeepTeal
                    ),
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(Modifier.height(28.dp))

                Button(
                    onClick = { viewModel.login(phone, password) },
                    enabled = uiState !is AuthUiState.Loading,
                    colors = ButtonDefaults.buttonColors(containerColor = WathbDeepTeal),
                    modifier = Modifier.fillMaxWidth().height(52.dp)
                ) {
                    if (uiState is AuthUiState.Loading) {
                        CircularProgressIndicator(
                            modifier  = Modifier.height(20.dp),
                            strokeWidth = 2.dp,
                            color     = Color.White
                        )
                    } else {
                        Text("دخول", style = MaterialTheme.typography.labelLarge, color = Color.White)
                    }
                }

                Spacer(Modifier.height(16.dp))

                TextButton(onClick = onNavigateToRegister) {
                    Text(
                        "ليس لديك حساب؟ سجّل الآن",
                        style = MaterialTheme.typography.bodyMedium,
                        color = WathbTeal
                    )
                }
            }
        }
    }
}
