from accounts.models import Role, User


class ObserverEmailBackend:
    """Observers sign in to the web dashboard with email and password. Phone sign-in (the mobile
    apps) never matches an observer: their phone field holds a placeholder that is not a number."""

    def authenticate(self, request, email=None, password=None, **kwargs):
        if not email or not password:
            return None
        try:
            user = User.objects.get(email__iexact=email.strip(), role=Role.OBSERVER)
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            return None
        if user.is_active and user.check_password(password):
            return user
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id, role=Role.OBSERVER)
        except User.DoesNotExist:
            return None
