package com.yawmiyati.app.ui.screens.worker

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.yawmiyati.app.viewmodels.nowInGaza
import com.yawmiyati.app.viewmodels.WorkerApplicationsViewModel
import com.yawmiyati.app.viewmodels.AssignmentsViewModel
import kotlinx.coroutines.delay
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.compose.runtime.produceState
import androidx.compose.runtime.LaunchedEffect

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkerMyWorkScreen(
    onManageAssignment: (assignmentId: String, workerPhone: String, businessPhone: String, assignmentStatus: String) -> Unit
) {
    var selectedTab by rememberSaveable { mutableIntStateOf(0) }
    // Shared by «طلباتي» and «مهامي»: a job moves from one to the other at its start time.
    val applicationsViewModel: WorkerApplicationsViewModel = viewModel()
    val assignmentsViewModel: AssignmentsViewModel = viewModel()
    val now by produceState(nowInGaza()) {
        while (true) {
            delay(60_000)
            value = nowInGaza()
        }
    }
    // Fresh lists each time the worker comes back (e.g. from the task details).
    LaunchedEffect(Unit) {
        applicationsViewModel.load()
        assignmentsViewModel.loadAssignments()
    }

    Column(modifier = Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.statusBars)) {
        TabRow(selectedTabIndex = selectedTab) {
            Tab(selected = selectedTab == 0, onClick = { selectedTab = 0 }) {
                Text("طلباتي", modifier = Modifier.padding(vertical = 12.dp))
            }
            Tab(selected = selectedTab == 1, onClick = { selectedTab = 1 }) {
                Text("مهامي", modifier = Modifier.padding(vertical = 12.dp))
            }
            Tab(selected = selectedTab == 2, onClick = { selectedTab = 2 }) {
                Text("أجوري", modifier = Modifier.padding(vertical = 12.dp))
            }
        }
        Box(modifier = Modifier.weight(1f)) {
            when (selectedTab) {
                0 -> WorkerApplicationsScreen(
                    viewModel = applicationsViewModel,
                    assignmentsViewModel = assignmentsViewModel,
                    now = now,
                    onManageAssignment = onManageAssignment,
                )
                1 -> WorkerAssignmentsScreen(
                    viewModel = assignmentsViewModel,
                    now = now,
                    onManageAssignment = onManageAssignment,
                )
                2 -> WorkerWagesScreen()
            }
        }
    }
}
