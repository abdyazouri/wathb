package com.yawmiyati.app

import com.yawmiyati.app.navigation.Screen
import com.yawmiyati.app.navigation.startRouteFor
import org.junit.Assert.assertEquals
import org.junit.Test

/** With fingerprint/face login on, a saved session never opens without the unlock screen. */
class StartRouteTest {

    private val home = Screen.WorkerHome.route

    @Test fun `no session goes to login`() {
        assertEquals(Screen.Login.route, startRouteFor(isLoggedIn = false, biometricLogin = false, homeRoute = home))
        assertEquals(Screen.Login.route, startRouteFor(isLoggedIn = false, biometricLogin = true, homeRoute = home))
    }

    @Test fun `session with biometric login goes to unlock, not home`() =
        assertEquals(Screen.Unlock.route, startRouteFor(isLoggedIn = true, biometricLogin = true, homeRoute = home))

    @Test fun `session without biometric login goes home`() =
        assertEquals(home, startRouteFor(isLoggedIn = true, biometricLogin = false, homeRoute = home))
}
