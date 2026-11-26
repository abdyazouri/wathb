package com.yawmiyati.app.ui.screens.business

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.yawmiyati.app.data.api.AssignmentResponse
import com.yawmiyati.app.ui.components.EmptyState
import com.yawmiyati.app.ui.components.ErrorMessage
import com.yawmiyati.app.ui.components.LoadingIndicator
import com.yawmiyati.app.ui.utils.formatArabicDate
import com.yawmiyati.app.viewmodels.AssignmentActionState
import com.yawmiyati.app.viewmodels.AssignmentsUiState
import com.yawmiyati.app.viewmodels.AssignmentsViewModel
import com.yawmiyati.app.ui.utils.StatusLabels
import com.yawmiyati.app.ui.components.PullableState
import com.yawmiyati.app.ui.components.Refreshable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import com.yawmiyati.app.ui.components.NotDoneDialog

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BusinessAssignmentsTab(
    onManageAssignment: (assignmentId: String, workerPhone: String, assignmentStatus: String) -> Unit = { _, _, _ -> },
    onOpenPayment: (wageId: String) -> Unit = {},
    viewModel: AssignmentsViewModel = viewModel()
) {
    val paymentToOpen by viewModel.paymentToOpen.collectAsState()
    LaunchedEffect(paymentToOpen) {
        paymentToOpen?.let { wageId ->
            viewModel.paymentOpened()
            onOpenPayment(wageId)  // «تأكيد ودفع الأجر» → «تحويل الأجر»
        }
    }
    val uiState by viewModel.uiState.collectAsState()
    val actionState by viewModel.actionState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(actionState) {
        when (actionState) {
            is AssignmentActionState.Success -> {
                snackbarHostState.showSnackbar("تم بنجاح")
                viewModel.resetActionState()
            }
            is AssignmentActionState.Error -> {
                snackbarHostState.showSnackbar((actionState as AssignmentActionState.Error).message)
                viewModel.resetActionState()
            }
            else -> {}
        }
    }

    Scaffold(snackbarHost = { SnackbarHost(snackbarHostState) }) { padding ->
        Refreshable(
            isRefreshing = false,
            onRefresh = { viewModel.loadAssignments() },
            modifier = Modifier.padding(padding)
        ) {
            when (val state = uiState) {
                is AssignmentsUiState.Loading -> PullableState { LoadingIndicator(modifier = Modifier.fillMaxSize()) }
                is AssignmentsUiState.Empty   -> PullableState { EmptyState(
                    message = "لا توجد مهام نشطة حالياً",
                    modifier = Modifier.fillMaxSize()
                ) }
                is AssignmentsUiState.Error   -> PullableState { ErrorMessage(
                    message = state.message,
                    onRetry = { viewModel.loadAssignments() },
                    modifier = Modifier.fillMaxSize()
                ) }
                is AssignmentsUiState.Success -> {
                    LazyColumn(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(horizontal = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        item { Spacer(Modifier.height(8.dp)) }
                        items(state.assignments, key = { it.id }) { assignment ->
                            BusinessAssignmentCard(
                                assignment = assignment,
                                isActionLoading = actionState is AssignmentActionState.Loading,
                                onComplete = { viewModel.businessComplete(assignment.id) },
                            onNotDone = { category, notes -> viewModel.reportNotDone(assignment.id, category, notes) },
                                onManage = { onManageAssignment(assignment.id, assignment.workerPhone, assignment.status) }
                            )
                        }
                        item { Spacer(Modifier.height(16.dp)) }
                    }
                }
            }
        }
    }
}

@Composable
private fun BusinessAssignmentCard(
    assignment: AssignmentResponse,
    isActionLoading: Boolean,
    onComplete: () -> Unit = {},
    onNotDone: (category: String, notes: String) -> Unit = { _, _ -> },
    onManage: () -> Unit = {}
) {
    var showNotDone by remember { mutableStateOf(false) }
    if (showNotDone) {
        NotDoneDialog(
            isLoading = isActionLoading,
            onConfirm = { category, notes -> showNotDone = false; onNotDone(category, notes) },
            onDismiss = { showNotDone = false }
        )
    }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = assignment.jobTitle,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f)
                )
                AssignmentStatusBadge(assignment.status)
            }

            Text(
                text = "العامل: ${assignment.workerPhone}",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            if (!assignment.jobWorkDate.isNullOrBlank()) {
                Text(
                    text = "يوم العمل: ${formatArabicDate(assignment.jobWorkDate)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }

            val workerAsked = assignment.completionStatus == "SUBMITTED" &&
                assignment.completionRequestedByWorker == true
            when {
                assignment.status in listOf("ACCEPTED", "ACTIVE") && workerAsked -> {
                    // The worker pressed «أتممت يوم عملي واطلب أجري».
                    Surface(
                        color = MaterialTheme.colorScheme.primaryContainer,
                        shape = MaterialTheme.shapes.small,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(
                            "أتمّ العامل يوم العمل ويطلب أجره. إن لم ترد خلال ٢٤ ساعة يتأكد الإتمام تلقائيًا.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)
                        )
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = onComplete,
                            enabled = !isActionLoading,
                            modifier = Modifier.weight(1f)
                        ) { Text("تأكيد ودفع الأجر") }
                        OutlinedButton(
                            onClick = { showNotDone = true },
                            enabled = !isActionLoading,
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                            modifier = Modifier.weight(1f)
                        ) { Text("لم يتم العمل") }
                    }
                }
                assignment.status in listOf("ACCEPTED", "ACTIVE") && assignment.completionStatus == "DISPUTED" -> {
                    Text(
                        if (assignment.completionRequestedByWorker == true) "أبلغت أن العمل لم يتم — النزاع لدى مشرف وَثْب."
                        else "اعترض العامل على إتمام العمل — النزاع لدى مشرف وَثْب.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error
                    )
                }
                assignment.status in listOf("ACCEPTED", "ACTIVE") -> {
                    // The worker has not asked (yet): the business can still record completion.
                    Button(
                        onClick = onComplete,
                        enabled = !isActionLoading,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        if (isActionLoading) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(18.dp),
                                strokeWidth = 2.dp,
                                color = MaterialTheme.colorScheme.onPrimary
                            )
                        } else {
                            Text("تأكيد إتمام العمل")
                        }
                    }
                }
                assignment.status == "COMPLETED" -> {
                    Text(
                        "✓ بانتظار إقرار العامل",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

@Composable
private fun AssignmentStatusBadge(status: String) {
    val label = StatusLabels.assignment(status)
    val color = when (status) {
        "OFFERED"   -> MaterialTheme.colorScheme.primary
        "ACCEPTED"  -> MaterialTheme.colorScheme.tertiary
        "DECLINED"  -> MaterialTheme.colorScheme.error
        "ACTIVE"    -> MaterialTheme.colorScheme.secondary
        "COMPLETED" -> MaterialTheme.colorScheme.tertiary
        "CANCELLED" -> MaterialTheme.colorScheme.error
        else        -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Surface(
        color = color.copy(alpha = 0.12f),
        shape = MaterialTheme.shapes.small
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = color,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
        )
    }
}
