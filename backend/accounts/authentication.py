from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

from accounts.models import Role


class AppJWTAuthentication(JWTAuthentication):
    """JWT for the mobile apps. An observer token is refused (403) on every API endpoint:
    observers only use the read-only web dashboard."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if user.role == Role.OBSERVER:
            raise PermissionDenied("هذا الحساب للقراءة فقط عبر لوحة المتابعة.")
        return user
