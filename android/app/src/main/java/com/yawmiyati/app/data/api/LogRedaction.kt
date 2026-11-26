package com.yawmiyati.app.data.api

private val SECRET_FIELDS =
    Regex("\"(code|password|new_password|old_password|access|refresh)\"\\s*:\\s*\"[^\"]*\"")

/**
 * Debug HTTP logs print request and response bodies. Mask the payment code, passwords
 * and JWTs so they never reach Logcat.
 */
fun redactSecrets(line: String): String =
    SECRET_FIELDS.replace(line) { "\"${it.groupValues[1]}\":\"***\"" }
