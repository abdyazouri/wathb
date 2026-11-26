import logging
import re

from rest_framework import exceptions
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)

_ARABIC_LETTER = re.compile(r"[؀-ۿ]")

VALIDATION_ERROR_DETAIL = "بعض الحقول غير صالحة."
INVALID_VALUE_DETAIL = "قيمة غير صالحة."

# Last-resort Arabic for any message that still reached here without Arabic text.
_GENERIC_DETAIL_BY_STATUS = {
    400: "الطلب غير صالح.",
    401: "يجب تسجيل الدخول.",
    403: "ليس لديك صلاحية للقيام بهذا الإجراء.",
    404: "غير موجود.",
    405: "هذه العملية غير مسموح بها.",
    409: "يتعارض الطلب مع الحالة الحالية.",
    413: "حجم الطلب كبير جداً.",
    415: "نوع المحتوى غير مدعوم.",
    429: "تم تقييد الطلب. الرجاء المحاولة لاحقاً.",
}
_GENERIC_DETAIL = "حدث خطأ. الرجاء المحاولة لاحقاً."


def is_arabic(text):
    return bool(_ARABIC_LETTER.search(str(text)))


def arabic_or_generic(text, status_code):
    """Return text unchanged if it contains Arabic, else a generic Arabic message."""
    if is_arabic(text):
        return text
    logger.warning("Non-Arabic API error message replaced (status %s): %s", status_code, str(text)[:200])
    return _GENERIC_DETAIL_BY_STATUS.get(status_code, _GENERIC_DETAIL)


def _arabic_field_errors(value):
    if isinstance(value, dict):
        return {k: _arabic_field_errors(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_arabic_field_errors(v) for v in value]
    if is_arabic(value):
        return value
    logger.warning("Non-Arabic field error replaced: %s", str(value)[:200])
    return INVALID_VALUE_DETAIL


def _first_message(value):
    if isinstance(value, list):
        return _first_message(value[0]) if value else ""
    if isinstance(value, dict):
        return _first_message(next(iter(value.values()))) if value else ""
    return str(value)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        error_code = "error"
        fields = None

        data = response.data
        if isinstance(exc, exceptions.Throttled):
            # DRF formats the wait time before translating, so its suffix stays English.
            detail = "تم تقييد الطلب."
            if exc.wait is not None:
                detail += f" الرجاء المحاولة بعد {exc.wait} ثانية."
        elif isinstance(data, dict) and "detail" in data:
            detail = str(data["detail"])
        elif isinstance(data, dict):
            error_code = "validation_error"
            detail = VALIDATION_ERROR_DETAIL
            fields = _arabic_field_errors(data)
        else:
            # e.g. ValidationError("...") raised with a bare message → list
            detail = _first_message(data)

        response.data = {
            "error": error_code,
            "detail": arabic_or_generic(detail, response.status_code),
        }
        if fields:
            response.data["fields"] = fields

    return response
