package com.yawmiyati.app.ui.screens.worker

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.yawmiyati.app.data.api.JobApplicationResponse
import com.yawmiyati.app.ui.components.EmptyState
import com.yawmiyati.app.ui.components.ErrorMessage
import com.yawmiyati.app.ui.components.LoadingIndicator
import com.yawmiyati.app.ui.utils.formatArabicDate
import com.yawmiyati.app.viewmodels.WorkerAppsActionState
import com.yawmiyati.app.viewmodels.WorkerAppsUiState
import com.yawmiyati.app.viewmodels.WorkerApplicationsViewModel
import com.yawmiyati.app.ui.utils.StatusLabels
import com.yawmiyati.app.viewmodels.splitMyWork
import com.yawmiyati.app.viewmodels.nowInGaza
import com.yawmiyati.app.viewmodels.MyApplicationsItem
import com.yawmiyati.app.viewmodels.AssignmentsViewModel
import com.yawmiyati.app.viewmodels.AssignmentsUiState
import com.yawmiyati.app.viewmodels.AssignmentActionState
import java.time.LocalDateTime
import androidx.compose.material3.pulltorefresh.PullToRefreshBox

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkerApplicationsScreen(
    onBack: (() -> Unit)? = null,
    viewModel: WorkerApplicationsViewModel = viewModel(),
    assignmentsViewModel: AssignmentsViewModel = viewModel(),
    now: LocalDateTime = nowInGaza(),
    onManageAssignment: (assignmentId: String, workerPhone: String, businessPhone: String, assignmentStatus: String) -> Unit = { _, _, _, _ -> },
) {
    val uiState by viewModel.uiState.collectAsState()
    val actionState by viewModel.actionState.collectAsState()
    val assignmentsState by assignmentsViewModel.uiState.collectAsState()
    val assignmentActionState by assignmentsViewModel.actionState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(actionState) {
        if (actionState is WorkerAppsActionState.Error) {
            snackbarHostState.showSnackbar((actionState as WorkerAppsActionState.Error).message)
            viewModel.resetActionState()
        }
    }
    LaunchedEffect(assignmentActionState) {
        when (val s = assignmentActionState) {
            is AssignmentActionState.Success -> {
                viewModel.load()  // accepting/declining an offer changes the application too
                snackbarHostState.showSnackbar("تم بنجاح")
                assignmentsViewModel.resetActionState()
            }
            is AssignmentActionState.Error -> {
                snackbarHostState.showSnackbar(s.message)
                assignmentsViewModel.resetActionState()
            }
            else -> {}
        }
    }
    val reload = {
        viewModel.load()
        assignmentsViewModel.loadAssignments()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("طلباتي") },
                navigationIcon = {
                    if (onBack != null) IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "رجوع")
                    }
                }
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) }
    ) { padding ->
        val appsError = uiState as? WorkerAppsUiState.Error
        val assignmentsError = assignmentsState as? AssignmentsUiState.Error
        when {
            uiState is WorkerAppsUiState.Loading || assignmentsState is AssignmentsUiState.Loading ->
                LoadingIndicator(modifier = Modifier.padding(padding))
            appsError != null || assignmentsError != null -> ErrorMessage(
                message = appsError?.message ?: assignmentsError!!.message,
                onRetry = reload,
                modifier = Modifier.padding(padding)
            )
            else -> {
                val applications = (uiState as? WorkerAppsUiState.Success)?.applications.orEmpty()
                val assignments = (assignmentsState as? AssignmentsUiState.Success)?.assignments.orEmpty()
                val items = splitMyWork(applications, assignments, now).applications
                PullToRefreshBox(
                    isRefreshing = false,
                    onRefresh = reload,
                    modifier = Modifier.padding(padding).fillMaxSize()
                ) {
                    if (items.isEmpty()) {
                        EmptyState(message = "لم تتقدم لأي وظيفة بعد", modifier = Modifier.fillMaxSize())
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            item { Spacer(Modifier.height(8.dp)) }
                            items(items, key = {
                                when (it) {
                                    is MyApplicationsItem.Offer -> "offer-${it.assignment.id}"
                                    is MyApplicationsItem.Application -> "app-${it.application.id}"
                                }
                            }) { item ->
                                when (item) {
                                    is MyApplicationsItem.Offer -> {
                                        val a = item.assignment
                                        AssignmentCard(
                                            assignment = a,
                                            started = false,
                                            isActionLoading = assignmentActionState is AssignmentActionState.Loading,
                                            onAccept = { assignmentsViewModel.acceptAssignment(a.id) },
                                            onDecline = { assignmentsViewModel.declineAssignment(a.id) },
                                            onManage = { onManageAssignment(a.id, a.workerPhone, a.businessPhone ?: "", a.status) },
                                        )
                                    }
                                    is MyApplicationsItem.Application -> ApplicationCard(
                                        app = item.application,
                                        isActionLoading = actionState is WorkerAppsActionState.Loading,
                                        onWithdraw = { viewModel.withdraw(item.application.job, item.application.id) }
                                    )
                                }
                            }
                            item { Spacer(Modifier.height(16.dp)) }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ApplicationCard(
    app: JobApplicationResponse,
    isActionLoading: Boolean,
    onWithdraw: () -> Unit,
) {
    var showConfirm by remember { mutableStateOf(false) }

    if (showConfirm) {
        AlertDialog(
            onDismissRequest = { showConfirm = false },
            title = { Text("سحب الطلب") },
            text  = { Text("هل تريد سحب طلبك لـ\"${app.jobTitle}\"؟") },
            confirmButton = {
                Button(
                    onClick = { showConfirm = false; onWithdraw() },
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
                ) { Text("سحب") }
            },
            dismissButton = {
                TextButton(onClick = { showConfirm = false }) { Text("إلغاء") }
            }
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
                    text = app.jobTitle,
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.weight(1f)
                )
                StatusChip(app.status)
            }
            Text(
                text = "تاريخ التقديم: ${formatArabicDate(app.appliedAt)}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            if (app.coverNote.isNotBlank()) {
                Text(
                    text = app.coverNote,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (app.status in listOf("PENDING", "OFFERED")) {
                OutlinedButton(
                    onClick = { showConfirm = true },
                    enabled = !isActionLoading,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor = MaterialTheme.colorScheme.error
                    )
                ) { Text("سحب الطلب") }
            }
        }
    }
}

@Composable
private fun StatusChip(status: String) {
    val label = StatusLabels.applicationForWorker(status)
    val color = when (status) {
        "PENDING"   -> MaterialTheme.colorScheme.secondary
        "OFFERED"   -> MaterialTheme.colorScheme.primary
        "ACCEPTED"  -> MaterialTheme.colorScheme.tertiary
        "REJECTED"  -> MaterialTheme.colorScheme.error
        "WITHDRAWN" -> MaterialTheme.colorScheme.onSurfaceVariant
        "CANCELLED" -> MaterialTheme.colorScheme.error
        else        -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Text(text = label, style = MaterialTheme.typography.labelSmall, color = color)
}
