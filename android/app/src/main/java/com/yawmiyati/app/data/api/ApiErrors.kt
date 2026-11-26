package com.yawmiyati.app.data.api

import com.google.gson.Gson
import com.google.gson.JsonElement
import com.google.gson.JsonObject

/** Turns a server error body into the Arabic message shown to the user. */
object ApiErrors {

    /**
     * The server sends {"error", "detail", "fields"?}. For a validation error the detail is
     * only the generic «بعض الحقول غير صالحة.», so the per-field reasons in "fields" win
     * (one line per field, e.g. «رقم الهاتف هذا مسجّل مسبقاً.»).
     */
    fun message(body: String?): String {
        if (body.isNullOrBlank()) return "خطأ غير معروف"
        return try {
            val json = Gson().fromJson(body, JsonObject::class.java)
            val fields = json["fields"]?.let { messages(it) }.orEmpty()
            when {
                fields.isNotEmpty() -> fields.distinct().joinToString("\n")
                json.has("detail") -> json["detail"].asString
                json.has("non_field_errors") -> messages(json["non_field_errors"]).firstOrNull() ?: "بيانات غير صالحة"
                else -> messages(json).firstOrNull() ?: "خطأ في الطلب"
            }
        } catch (_: Exception) {
            "فشل الطلب"
        }
    }

    /** First message of each field, in order; nested objects are flattened. */
    private fun messages(element: JsonElement): List<String> = when {
        element.isJsonPrimitive -> listOf(element.asString)
        element.isJsonArray -> element.asJsonArray.firstOrNull()?.let { messages(it) }.orEmpty()
        element.isJsonObject -> element.asJsonObject.entrySet().flatMap { (_, v) -> messages(v) }
        else -> emptyList()
    }
}
