package com.yawmiyati.app

import com.google.gson.Gson
import com.yawmiyati.app.data.api.AppConfigResponse
import org.junit.Assert.assertEquals
import org.junit.Test

/** GET app/config/ sends snake_case keys; camelCase-only fields left the support button and forced update dead. */
class AppConfigTest {

    @Test
    fun `parses the server's snake_case app config`() {
        // Response of https://wathb-api2.onrender.com/api/v1/app/config/ (Nov 2026).
        val body = """{"min_supported_version_code":1,"latest_version_code":1,""" +
            """"apk_download_url":"https://wathb.quotefather.com/","support_whatsapp":"+970598783757"}"""

        val config = Gson().fromJson(body, AppConfigResponse::class.java)

        assertEquals(1, config.minSupportedVersionCode)
        assertEquals(1, config.latestVersionCode)
        assertEquals("https://wathb.quotefather.com/", config.apkDownloadUrl)
        assertEquals("+970598783757", config.supportWhatsapp)
    }

    @Test
    fun `missing keys fall back to defaults instead of nulls`() {
        val config = Gson().fromJson("""{"min_supported_version_code":3}""", AppConfigResponse::class.java)

        assertEquals(3, config.minSupportedVersionCode)
        assertEquals("", config.supportWhatsapp)
        assertEquals("", config.apkDownloadUrl)
    }
}
