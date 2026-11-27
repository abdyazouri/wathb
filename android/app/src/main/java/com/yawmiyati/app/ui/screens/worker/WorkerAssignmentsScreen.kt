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
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.yawmiyati.app.data.api.AssignmentResponse
import com.yawmiyati.app.ui.components.EmptyState
import com.yawmiyati.app.ui.components.ErrorMessage
import com.yawmiyati.app.ui.components.LoadingIndicator
import com.yawmiyati.app.ui.components.rememberWageAcknowledgeGate
import com.yawmiyati.app.ui.utils.formatArabicDate
import com.yawmiyati.app.ui.utils.formatArabicTime
import com.yawmiyati.app.ui.utils.formatArabicWage
import com.yawmiyati.app.ui.utils.toArabic
import com.yawmiyati.app.viewmodels.AssignmentActionState
import com.yawmiyati.app.viewmodels.AssignmentsUiState
import com.yawmiyati.app.viewmodels.AssignmentsViewModel
import com.yawmiyati.app.ui.utils.StatusLabels
import com.yawmiyati.app.viewmodels.workStart
import com.yawmiyati.app.viewmodels.splitMyWork
import com.yawmiyati.app.viewmodels.nowInGaza
import java.time.LocalDateTime
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import com.yawmiyati.app.ui.components.PullableState
import com.yawmiyati.app.ui.utils.TermLabels
import com.yawmiyati.app.viewmodels.canRequestWage
import com.yawmiyati.app.ui.components.RequestWageDialog

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkerAssignmentsScreen(
    onBack: (() -> Unit)? = null,
    onManageAssignment: (assignmentId: String, workerPhone: String, businessPhone: String, assignmentStatus: String) -> Unit = { _, _, _, _ -> },
    viewModel: AssignmentsViewModel = viewModel(),
    now: LocalDateTime = nowInGaza(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val actionState by viewModel.actionState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    var disputingObligationId by remember { mutableStateOf<String?>(null) }
    val acknowledge = rememberWageAcknowledgeGate { id, password -> viewModel.acknowledgeWage(id, password) }
    var disputeReason by remember { mutableStateOf("") }

    LaunchedEffect(actionState) {
        when (actionState) {
            is AssignmentActionState.Error -> {
                snackbarHostState.showSnackbar((actionState as AssignmentActionState.Error).message)
                viewModel.resetActionState()
            }
            is AssignmentActionState.Success -> {
                snackbarHostState.showSnackbar("تم بنجاح")
                viewModel.resetActionState()
            }
            else -> {}
        }
    }

    if (disputingObligationId != null) {
        AlertDialog(
            onDismissRequest = { disputingObligationId = null; disputeReason = "" },
            title = { Text("الاعتراض على الأجر") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("اشرح سبب الاعتراض:")
                    OutlinedTextField(
                        value = disputeReason,
                        onValueChange = { disputeReason = it },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 2
                    )
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        disputingObligationId?.let { oblId ->
                            viewModel.disputeWage(oblId, disputeReason)
                            disputingObligationId = null
                            disputeReason = ""
                        }
                    },
                    enabled = disputeReason.isNotBlank()
                ) { Text("تأكيد الاعتراض") }
            },
            dismissButton = {
                TextButton(onClick = { disputingObligationId = null; disputeReason = "" }) { Text("إلغاء") }
            }
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("مهامي") },
                navigationIcon = {
                    if (onBack != null) IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "رجوع")
                    }
                }
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) }
    ) { padding ->
        when (val state = uiState) {
            is AssignmentsUiState.Loading -> LoadingIndicator(modifier = Modifier.padding(padding))
            is AssignmentsUiState.Empty   -> EmptyState(
                message = NO_TASKS_YET,
                modifier = Modifier.padding(padding).fillMaxSize()
            )
            is AssignmentsUiState.Error   -> ErrorMessage(
                message = state.message,
                onRetry = { viewModel.loadAssignments() },
                modifier = Modifier.padding(padding)
            )
            is AssignmentsUiState.Success -> {
                // Only jobs whose start time has come; earlier ones are in «طلباتي».
                val tasks = splitMyWork(emptyList(), state.assignments, now).tasks
                PullToRefreshBox(
                    isRefreshing = false,
                    onRefresh = { viewModel.loadAssignments() },
                    modifier = Modifier.padding(padding).fillMaxSize()
                ) {
                if (tasks.isEmpty()) {
                    PullableState { EmptyState(message = NO_TASKS_YET, modifier = Modifier.fillMaxSize()) }
                } else LazyColumn(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    item { Spacer(Modifier.height(8.dp)) }
                    items(tasks, key = { it.id }) { assignment ->
                        AssignmentCard(
                            assignment = assignment,
                            started = true,
                            onRequestWage = { viewModel.requestWage(assignment.id) },
                            isActionLoading = actionState is AssignmentActionState.Loading,
                            onAccept  = { viewModel.acceptAssignment(assignment.id) },
                            onDecline = { viewModel.declineAssignment(assignment.id) },
                            onManage  = { onManageAssignment(assignment.id, assignment.workerPhone, assignment.businessPhone ?: "", assignment.status) },
                            onAcknowledgeWage = { oblId -> acknowledge(oblId) },
                            onDisputeWage = { oblId -> disputingObligationId = oblId }
                        )
                    }
                    item { Spacer(Modifier.height(16.dp)) }
                }
                }
            }
        }
    }
}

/** Where the worker's wage request stands, shown on the task card. */
@Composable
private fun WageRequestStatus(assignment: AssignmentResponse) {
    val byWorker = assignment.completionRequestedByWorker == true
    val (text, color) = when (assignment.completionStatus) {
        "SUBMITTED" -> if (byWorker) {
            "✓ أرسلت طلب أجرك. بانتظار صاحب العمل، ويتأكد تلقائيًا بعد ٢٤ ساعة." to MaterialTheme.colorScheme.tertiary
        } else {
            "سجّل صاحب العمل إتمام العمل — أكّده أو اعترض من صفحة المهمة." to MaterialTheme.colorScheme.primary
        }
        "DISPUTED" -> if (byWorker) {
            "قال صاحب العمل إن العمل لم يتم، والنزاع لدى مشرف وَثْب." to MaterialTheme.colorScheme.error
        } else {
            "تم الاعتراض على إتمام العمل، والنزاع لدى مشرف وَثْب." to MaterialTheme.colorScheme.error
        }
        else -> return
    }
    Text(text, style = MaterialTheme.typography.bodyMedium, color = color)
}

private const val NO_TASKS_YET = "لا توجد مهام بدأت بعد.\nالمهمة المقبولة تنتقل إلى هنا عند بدء وقت العمل."

/** [started]: the job's start time has come («مهامي»); otherwise it is shown in «طلباتي». */
@Composable
internal fun AssignmentCard(
    assignment: AssignmentResponse,
    started: Boolean,
    onRequestWage: () -> Unit = {},
    isActionLoading: Boolean,
    onAccept: () -> Unit,
    onDecline: () -> Unit,
    onManage: () -> Unit = {},
    onAcknowledgeWage: (obligationId: String) -> Unit = {},
    onDisputeWage: (obligationId: String) -> Unit = {}
) {
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
                text = assignment.businessName,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            if (!assignment.offeredAt.isNullOrBlank()) {
                Text(
                    text = "تاريخ العرض: ${formatArabicDate(assignment.offeredAt)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }

            if (!assignment.acceptedAt.isNullOrBlank()) {
                Text(
                    text = "تاريخ القبول: ${formatArabicDate(assignment.acceptedAt)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }

            // Show job terms on OFFERED cards so worker can review before accepting
            if (assignment.status == "OFFERED") {
                if (!assignment.jobWorkDate.isNullOrBlank()) {
                    Text(
                        text = "يوم العمل: ${formatArabicDate(assignment.jobWorkDate)}",
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                if (!assignment.jobStartTime.isNullOrBlank() && !assignment.jobEndTime.isNullOrBlank()) {
                    Text(
                        text = "الوقت: ${formatArabicTime(assignment.jobStartTime)} — ${formatArabicTime(assignment.jobEndTime)}",
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                if (!assignment.jobLocationCity.isNullOrBlank()) {
                    Text(
                        text = "الموقع: ${assignment.jobLocationCity}${if (!assignment.jobLocationAddress.isNullOrBlank()) "، ${assignment.jobLocationAddress}" else ""}",
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                if (assignment.jobWageAmount != null && !assignment.jobWageCurrency.isNullOrBlank()) {
                    val basisLabel = when (assignment.jobWageBasis) {
                        "PER_DAY"  -> "يومي"
                        "PER_HOUR" -> "بالساعة"
                        "PER_TASK" -> "بالمهمة"
                        else       -> assignment.jobWageBasis ?: ""
                    }
                    val wageStr = formatArabicWage(
                        assignment.jobWageAmount,
                        assignment.jobWageCurrency ?: "ILS",
                        assignment.jobWageBasis ?: ""
                    )
                    Text(
                        text = "الأجر: $wageStr ($basisLabel)",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
            }

            // Show agreed terms after acceptance
            val snap = assignment.termsSnapshot
            if (snap != null && assignment.status !in listOf("OFFERED", "DECLINED", "COMPLETED")) {
                val snapWageAmount = (snap["wage_amount"] as? Number)?.toLong()
                val snapCurrency = snap["wage_currency"] as? String
                val snapBasis = snap["wage_basis"] as? String
                val snapWorkDate = snap["work_date"] as? String
                val snapStart = snap["start_time"] as? String
                val snapEnd = snap["end_time"] as? String
                val snapCity = snap["location_city"] as? String
                val snapAddress = snap["location_address"] as? String

                Text(
                    text = "الشروط المتفق عليها",
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.primary
                )
                if (!snapWorkDate.isNullOrBlank())
                    Text("يوم العمل: ${formatArabicDate(snapWorkDate)}", style = MaterialTheme.typography.bodySmall)
                if (!snapStart.isNullOrBlank() && !snapEnd.isNullOrBlank())
                    Text("الوقت: ${formatArabicTime(snapStart)} — ${formatArabicTime(snapEnd)}", style = MaterialTheme.typography.bodySmall)
                if (!snapCity.isNullOrBlank())
                    Text("الموقع: $snapCity${if (!snapAddress.isNullOrBlank()) "، $snapAddress" else ""}", style = MaterialTheme.typography.bodySmall)
                if (snapWageAmount != null && !snapCurrency.isNullOrBlank()) {
                    val basisLabel = when (snapBasis) {
                        "PER_DAY"  -> "يومي"
                        "PER_HOUR" -> "بالساعة"
                        "PER_TASK" -> "بالمهمة"
                        else       -> snapBasis ?: ""
                    }
                    val wageStr = formatArabicWage(snapWageAmount, snapCurrency, snapBasis ?: "")
                    Text(
                        "الأجر: $wageStr ($basisLabel)",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
            }

            // Action buttons
            when (assignment.status) {
                "OFFERED" -> {
                    // Applying said "I'm interested"; this confirms "I'll come on these terms",
                    // and the terms are fixed for the wage and any dispute.
                    Text(
                        "اختارك صاحب العمل! راجع الشروط أعلاه وأكّد أنك ستحضر.",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.primary
                    )
                    val changed = assignment.changedTerms.orEmpty()
                    if (changed.isNotEmpty()) {
                        Surface(
                            color = MaterialTheme.colorScheme.errorContainer,
                            shape = MaterialTheme.shapes.small,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(
                                "تغيّر منذ تقدّمت: ${TermLabels.changed(changed)}",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onErrorContainer,
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)
                            )
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = onAccept,
                            enabled = !isActionLoading,
                            modifier = Modifier.weight(1f)
                        ) { Text("أؤكد حضوري") }
                        OutlinedButton(
                            onClick = onDecline,
                            enabled = !isActionLoading,
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                            modifier = Modifier.weight(1f)
                        ) { Text("لا أستطيع") }
                    }
                }
                "COMPLETED" -> {
                    val obligationId = assignment.wageObligationId
                    // «تأكيد الاستلام» only while the wage awaits the worker (older servers send no status).
                    val awaitingWorker = assignment.wageStatus?.let { it == "AWAITING_ACK" } ?: true
                    if (obligationId != null && !awaitingWorker) {
                        Text(
                            text = "الأجر: ${StatusLabels.wageForWorker(assignment.wageStatus)}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = if (assignment.wageStatus == "VERIFIED_PAID") MaterialTheme.colorScheme.tertiary
                                    else MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        OutlinedButton(onClick = onManage, modifier = Modifier.fillMaxWidth()) { Text("فتح المهمة") }
                    } else if (obligationId != null && snap != null) {
                        val snapAmount = (snap["wage_amount"] as? Number)?.toLong()
                        val snapCurrency = snap["wage_currency"] as? String ?: "ILS"
                        val snapBasis = snap["wage_basis"] as? String ?: ""
                        if (snapAmount != null) {
                            Text(
                                text = "أجرك: ${formatArabicWage(snapAmount, snapCurrency, snapBasis)}",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.primary
                            )
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(
                                onClick = { onAcknowledgeWage(obligationId) },
                                enabled = !isActionLoading,
                                modifier = Modifier.weight(1f)
                            ) { Text("تأكيد الاستلام") }
                            OutlinedButton(
                                onClick = { onDisputeWage(obligationId) },
                                enabled = !isActionLoading,
                                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                                modifier = Modifier.weight(1f)
                            ) { Text("اعتراض") }
                        }
                    } else {
                        // wage_obligation_id not yet in response — fallback to detail screen
                        Button(onClick = onManage, modifier = Modifier.fillMaxWidth()) {
                            Text("إقرار الأجر")
                        }
                    }
                }
                "ACCEPTED", "ACTIVE" -> {
                    WageRequestStatus(assignment)
                    if (assignment.canRequestWage(nowInGaza().toLocalDate())) {
                        var confirmRequest by remember { mutableStateOf(false) }
                        if (confirmRequest) {
                            RequestWageDialog(
                                onConfirm = { confirmRequest = false; onRequestWage() },
                                onDismiss = { confirmRequest = false }
                            )
                        }
                        Button(
                            onClick = { confirmRequest = true },
                            enabled = !isActionLoading,
                            modifier = Modifier.fillMaxWidth()
                        ) { Text("أتممت يوم عملي واطلب أجري") }
                    }
                    if (started) {
                        OutlinedButton(onClick = onManage, modifier = Modifier.fillMaxWidth()) { Text("فتح المهمة") }
                    } else {
                    val start = assignment.workStart()
                    if (start != null) {
                        Text(
                            "تبدأ ${formatArabicDate(start.toLocalDate().toString())} الساعة " +
                                "${formatArabicTime(start.toLocalTime().toString())}، وتنتقل إلى «مهامي» عند بدايتها.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.tertiary
                        )
                    }
                    OutlinedButton(onClick = onManage, modifier = Modifier.fillMaxWidth()) { Text("التفاصيل") }
                    }
                }
                // DECLINED/CANCELLED: no action
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
