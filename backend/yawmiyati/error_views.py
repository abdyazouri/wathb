"""Arabic JSON for errors Django raises outside DRF (unknown URL, server error)
on /api/ paths. Everything else keeps Django's default pages."""
from django.http import JsonResponse
from django.views import defaults


def _is_api(request):
    return request.path.startswith("/api/")


def not_found(request, exception=None):
    if _is_api(request):
        return JsonResponse({"error": "error", "detail": "غير موجود."}, status=404)
    return defaults.page_not_found(request, exception)


def server_error(request):
    if _is_api(request):
        return JsonResponse(
            {"error": "error", "detail": "حدث خطأ في الخادم. الرجاء المحاولة لاحقاً."},
            status=500,
        )
    return defaults.server_error(request)
