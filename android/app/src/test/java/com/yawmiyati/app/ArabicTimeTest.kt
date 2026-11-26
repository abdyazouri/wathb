package com.yawmiyati.app

import com.yawmiyati.app.ui.utils.formatArabicTime
import org.junit.Assert.assertEquals
import org.junit.Test

/** Times show on a 12-hour clock with صباحًا / مساءً. */
class ArabicTimeTest {

    @Test fun `morning`() = assertEquals("٧:٠٠ صباحًا", formatArabicTime("07:00:00"))
    @Test fun `afternoon`() = assertEquals("١:٣٠ مساءً", formatArabicTime("13:30"))
    @Test fun `noon is evening half`() = assertEquals("١٢:٠٠ مساءً", formatArabicTime("12:00"))
    @Test fun `midnight is 12 in the morning`() = assertEquals("١٢:١٥ صباحًا", formatArabicTime("00:15"))
    @Test fun `late evening`() = assertEquals("١١:٠٥ مساءً", formatArabicTime("23:05:00"))
    @Test fun `bad value falls back`() = assertEquals("abc", formatArabicTime("abc"))
}
