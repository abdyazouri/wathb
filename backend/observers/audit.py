from audit.models import AuditEvent


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or None


def log(request, action, user=None, **details):
    """Every observer sign-in, failed attempt, page view and export goes to the immutable audit log."""
    AuditEvent.objects.create(
        actor=user if user is not None else (request.user if request.user.is_authenticated else None),
        action=action,
        model_name="Observer",
        object_id=str(user.pk if user is not None else getattr(request.user, "pk", "") or ""),
        details=details,
        ip_address=client_ip(request),
    )
