import uuid
from django.db import models
from django.conf import settings


class NotificationType(models.TextChoices):
    APPLICATION_ACCEPTED = "APPLICATION_ACCEPTED", "تم قبول الطلب"
    APPLICATION_REJECTED = "APPLICATION_REJECTED", "تم رفض الطلب"
    JOB_OFFER = "JOB_OFFER", "عرض عمل"
    ATTENDANCE_DISPUTED = "ATTENDANCE_DISPUTED", "اعتراض على الحضور"
    COMPLETION_CONFIRMED = "COMPLETION_CONFIRMED", "تأكيد إتمام العمل"
    COMPLETION_DISPUTED = "COMPLETION_DISPUTED", "اعتراض على إتمام العمل"
    WAGE_DUE = "WAGE_DUE", "أجر مستحق"
    PAYMENT_DECLARED = "PAYMENT_DECLARED", "إعلان دفع الأجر"
    PAYMENT_VERIFIED = "PAYMENT_VERIFIED", "تأكيد دفع الأجر"
    PAYMENT_REJECTED = "PAYMENT_REJECTED", "رفض إعلان الدفع"
    DISPUTE_STATUS_CHANGED = "DISPUTE_STATUS_CHANGED", "تغيّر حالة النزاع"
    FUNDING_APPROVED = "FUNDING_APPROVED", "اعتماد التمويل"
    FUNDING_REJECTED = "FUNDING_REJECTED", "رفض التمويل"
    JOB_CANCELLED = "JOB_CANCELLED", "إلغاء الوظيفة"
    ASSIGNMENT_CANCELLED = "ASSIGNMENT_CANCELLED", "إلغاء المهمة"
    ATTENDANCE_SUBMITTED = "ATTENDANCE_SUBMITTED", "تسجيل حضور"
    COMPLETION_SUBMITTED = "COMPLETION_SUBMITTED", "تسجيل إتمام العمل"
    WAGE_REMINDER_1D = "WAGE_REMINDER_1D", "تذكير بإقرار الأجر (يوم)"
    WAGE_REMINDER_3D = "WAGE_REMINDER_3D", "تذكير بإقرار الأجر (٣ أيام)"
    WAGE_UNPAID_1D = "WAGE_UNPAID_1D", "تذكير بدفع الأجر (يوم)"
    WAGE_UNPAID_3D = "WAGE_UNPAID_3D", "تذكير بدفع الأجر (٣ أيام)"
    ATTENDANCE_AUTO_CONFIRMED = "ATTENDANCE_AUTO_CONFIRMED", "تأكيد تلقائي للحضور"
    COMPLETION_AUTO_CONFIRMED = "COMPLETION_AUTO_CONFIRMED", "تأكيد تلقائي لإتمام العمل"
    JOB_CREATED_BY_ADMIN = "JOB_CREATED_BY_ADMIN", "وظيفة أضافها المشرف نيابة عنك"
    JOB_PUBLISHED_BY_ADMIN = "JOB_PUBLISHED_BY_ADMIN", "وظيفة نشرها المشرف نيابة عنك"


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    notification_type = models.CharField(max_length=50, choices=NotificationType.choices)
    title = models.CharField(max_length=200)
    body = models.TextField()
    related_model = models.CharField(max_length=100, blank=True)
    related_id = models.CharField(max_length=100, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.notification_type} → {self.recipient.email}"
