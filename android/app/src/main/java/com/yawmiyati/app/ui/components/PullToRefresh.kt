package com.yawmiyati.app.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier

/** Swipe down to reload. Every screen that shows server data wraps its content in this. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Refreshable(
    isRefreshing: Boolean,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable BoxScope.() -> Unit,
) {
    PullToRefreshBox(
        isRefreshing = isRefreshing,
        onRefresh = onRefresh,
        modifier = modifier.fillMaxSize(),
        content = content,
    )
}

/**
 * The pull gesture only starts on scrollable content. Loading, empty and error states
 * don't scroll, so wrap them in this to make them pullable too.
 */
@Composable
fun PullableState(content: @Composable BoxScope.() -> Unit) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Box(Modifier.fillParentMaxSize(), contentAlignment = Alignment.Center, content = content)
        }
    }
}
