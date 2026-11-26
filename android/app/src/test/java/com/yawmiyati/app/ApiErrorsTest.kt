package com.yawmiyati.app

import com.yawmiyati.app.data.api.ApiErrors
import org.junit.Assert.assertEquals
import org.junit.Test

/** The user sees why a field was refused, not only «بعض الحقول غير صالحة.». */
class ApiErrorsTest {

    @Test
    fun `validation error shows the field reason instead of the generic detail`() {
        val body = """{"error":"validation_error","detail":"بعض الحقول غير صالحة.","fields":{"phone":["رقم الهاتف هذا مسجّل مسبقاً."]}}"""
        assertEquals("رقم الهاتف هذا مسجّل مسبقاً.", ApiErrors.message(body))
    }

    @Test
    fun `several invalid fields give one line each`() {
        val body = """{"error":"validation_error","detail":"بعض الحقول غير صالحة.","fields":{"phone":["رقم الهاتف هذا مسجّل مسبقاً."],"password":["كلمة المرور هذه تتكون من أرقام فقط.","كلمة المرور قصيرة جدًا."]}}"""
        assertEquals("رقم الهاتف هذا مسجّل مسبقاً.\nكلمة المرور هذه تتكون من أرقام فقط.", ApiErrors.message(body))
    }

    @Test
    fun `nested field errors are flattened`() {
        val body = """{"error":"validation_error","detail":"بعض الحقول غير صالحة.","fields":{"profile":{"full_name":["هذا الحقل مطلوب."]}}}"""
        assertEquals("هذا الحقل مطلوب.", ApiErrors.message(body))
    }

    @Test
    fun `plain error keeps its detail`() {
        assertEquals("كلمة المرور غير صحيحة.", ApiErrors.message("""{"error":"error","detail":"كلمة المرور غير صحيحة."}"""))
    }

    @Test
    fun `empty or non-JSON body`() {
        assertEquals("خطأ غير معروف", ApiErrors.message(""))
        assertEquals("فشل الطلب", ApiErrors.message("<html>Bad Gateway</html>"))
    }
}
