package com.yawmiyati.app

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.fragment.app.FragmentActivity
import com.yawmiyati.app.navigation.YawmiyatiNavGraph
import com.yawmiyati.app.ui.screens.AppUpdateGate
import com.yawmiyati.app.ui.theme.YawmiyatiTheme

// FragmentActivity (a ComponentActivity) is required by BiometricPrompt.
class MainActivity : FragmentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            YawmiyatiTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    AppUpdateGate {
                        YawmiyatiNavGraph()
                    }
                }
            }
        }
    }
}
