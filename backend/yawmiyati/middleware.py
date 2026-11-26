from django.utils import translation


class ApiArabicLocaleMiddleware:
    """Serve every /api/ request in Arabic, whatever Accept-Language says.

    Uses Django/DRF/SimpleJWT's built-in 'ar' catalogs plus the project catalog
    in backend/locale. Django admin and other non-API paths are left untouched.
    """

    API_PREFIX = "/api/"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(self.API_PREFIX):
            return self.get_response(request)
        previous = translation.get_language()
        translation.activate("ar")
        request.LANGUAGE_CODE = "ar"
        try:
            response = self.get_response(request)
            response.headers.setdefault("Content-Language", "ar")
            return response
        finally:
            translation.activate(previous)
