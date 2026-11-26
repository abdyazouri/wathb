import uuid
from django.db import models
from django.conf import settings


class DisputeCategory(models.TextChoices):
    WORKER_NO_SHOW = "WORKER_NO_SHOW", "العامل لم يحضر"
    ATTENDANCE_DISPUTED = "ATTENDANCE_DISPUTED", "خلاف على الحضور"
    WORK_INCOMPLETE = "WORK_INCOMPLETE", "العمل غير مكتمل"
    WAGE_DISPUTED = "WAGE_DISPUTED", "خلاف على مبلغ الأجر"
    PAYMENT_NOT_RECEIVED = "PAYMENT_NOT_RECEIVED", "لم يُستلَم الأجر"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT", "إثبات الدفع غير كافٍ"
    CONDITIONS_CHANGED = "CONDITIONS_CHANGED", "تغيّرت شروط العمل"
    CANCELLATION = "CANCELLATION", "مشكلة في الإلغاء"
    OTHER = "OTHER", "أخرى"


class DisputeStatus(models.TextChoices):
    OPEN = "OPEN", "مفتوح"
    IN_REVIEW = "IN_REVIEW", "قيد المراجعة"
    RESOLVED = "RESOLVED", "تم الحل"
    CLOSED = "CLOSED", "مغلق"


class Dispute(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=30, choices=DisputeCategory.choices)
    assignment = models.ForeignKey(
        "assignments.Assignment",
        on_delete=models.PROTECT,
        related_name="disputes",
    )
    wage_obligation = models.ForeignKey(
        "wages.WageObligation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="disputes",
    )
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="raised_disputes",
    )
    description = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=DisputeStatus.choices,
        default=DisputeStatus.OPEN,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_disputes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Dispute {self.category} — {self.raised_by.email} ({self.status})"


class DisputeEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dispute = models.ForeignKey(Dispute, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="dispute_events",
    )
    action = models.CharField(max_length=100)
    notes = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]

    def __str__(self):
        return f"{self.action} on {self.dispute} at {self.timestamp}"
