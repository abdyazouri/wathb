import uuid
from django.db import models
from django.utils import timezone
from django.conf import settings


class JobCategory(models.TextChoices):
    LOADING      = "LOADING",      "تحميل وتنزيل"
    CLEANING     = "CLEANING",     "تنظيف"
    CONSTRUCTION = "CONSTRUCTION", "بناء وترميم"
    AGRICULTURE  = "AGRICULTURE",  "زراعة"
    DELIVERY     = "DELIVERY",     "نقل وتوصيل"
    FOOD         = "FOOD",         "مطاعم ومطابخ"
    RETAIL       = "RETAIL",       "محلات وبيع"
    OTHER        = "OTHER",        "أخرى"


class WageBasis(models.TextChoices):
    PER_DAY = "PER_DAY", "يوم"
    PER_TASK = "PER_TASK", "مهمة"
    PER_HOUR = "PER_HOUR", "ساعة"


class PaymentMethod(models.TextChoices):
    # Owner decision: no cash. Only these three electronic methods are accepted.
    JAWWAL_PAY = "JAWWAL_PAY", "جوال باي"
    PALPAY = "PALPAY", "بال باي"
    BANK_OF_PALESTINE = "BANK_OF_PALESTINE", "بنك فلسطين"


class Currency(models.TextChoices):
    # Owner decision: ILS only. Any other currency is rejected by the API.
    ILS = "ILS", "شيكل"


class JobListingStatus(models.TextChoices):
    DRAFT = "DRAFT", "مسودة"
    PENDING_REVIEW = "PENDING_REVIEW", "قيد المراجعة"
    PUBLISHED = "PUBLISHED", "منشورة"
    FILLED = "FILLED", "اكتمل العدد"
    IN_PROGRESS = "IN_PROGRESS", "قيد التنفيذ"
    COMPLETED = "COMPLETED", "منتهية"
    CANCELLED = "CANCELLED", "ملغاة"


VALID_JOB_TRANSITIONS = {
    JobListingStatus.DRAFT: [JobListingStatus.PENDING_REVIEW, JobListingStatus.CANCELLED],
    JobListingStatus.PENDING_REVIEW: [JobListingStatus.PUBLISHED, JobListingStatus.DRAFT, JobListingStatus.CANCELLED],
    JobListingStatus.PUBLISHED: [JobListingStatus.FILLED, JobListingStatus.CANCELLED],
    # FILLED → PUBLISHED: a cancelled task freed a place before the work day (refresh_fill_status).
    JobListingStatus.FILLED: [JobListingStatus.PUBLISHED, JobListingStatus.IN_PROGRESS, JobListingStatus.CANCELLED],
    JobListingStatus.IN_PROGRESS: [JobListingStatus.COMPLETED, JobListingStatus.CANCELLED],
    JobListingStatus.COMPLETED: [],
    JobListingStatus.CANCELLED: [],
}


class ApplicationStatus(models.TextChoices):
    PENDING = "PENDING", "قيد الانتظار"
    OFFERED = "OFFERED", "تم تقديم عرض"
    ACCEPTED = "ACCEPTED", "مقبول"
    REJECTED = "REJECTED", "مرفوض"
    WITHDRAWN = "WITHDRAWN", "مسحوب"
    EXPIRED = "EXPIRED", "منتهي الصلاحية"
    CANCELLED = "CANCELLED", "ملغى"  # job was cancelled by the business


class JobListing(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(
        "accounts.BusinessProfile",
        on_delete=models.PROTECT,
        related_name="job_listings",
    )
    category = models.CharField(
        max_length=20, choices=JobCategory.choices, default=JobCategory.OTHER
    )
    title = models.CharField(max_length=300)
    description = models.TextField()
    location_address = models.CharField(max_length=500)
    location_city = models.CharField(max_length=100)
    work_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    num_workers_needed = models.PositiveIntegerField(default=1)
    required_skills = models.TextField(blank=True)
    wage_amount = models.PositiveBigIntegerField(help_text="Amount in minor currency units (e.g. agorot for ILS)")
    wage_currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.ILS)
    wage_basis = models.CharField(max_length=20, choices=WageBasis.choices, default=WageBasis.PER_DAY)
    # Set by the server: new jobs are paid with Jawwal Pay only. PALPAY and
    # BANK_OF_PALESTINE remain in the enum for older rows.
    payment_method = models.CharField(max_length=30, choices=PaymentMethod.choices, default=PaymentMethod.JAWWAL_PAY)
    attendance_requirements = models.TextField(blank=True)
    cancellation_policy = models.TextField(blank=True)
    additional_conditions = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=JobListingStatus.choices,
        default=JobListingStatus.DRAFT,
    )
    thumbnail_url = models.URLField(max_length=500, blank=True, default="")
    is_funded = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} — {self.business.legal_name} ({self.work_date})"

    def can_transition_to(self, new_status):
        return new_status in VALID_JOB_TRANSITIONS.get(self.status, [])

    def places_taken(self):
        """Tasks that hold a place: accepted, under way or done."""
        from assignments.models import AssignmentStatus
        return self.assignments.filter(
            status__in=[AssignmentStatus.ACCEPTED, AssignmentStatus.ACTIVE, AssignmentStatus.COMPLETED]
        ).count()

    def refresh_fill_status(self):
        """FILLED once the accepted tasks cover num_workers_needed; back to PUBLISHED when a cancellation
        frees a place and the work day has not passed, so other workers can apply again."""
        taken = self.places_taken()
        if self.status == JobListingStatus.PUBLISHED and taken >= self.num_workers_needed:
            self.status = JobListingStatus.FILLED
        elif (self.status == JobListingStatus.FILLED and taken < self.num_workers_needed
              and timezone.localdate() <= self.work_date):
            self.status = JobListingStatus.PUBLISHED
        else:
            return
        self.save(update_fields=["status"])

    def material_terms_snapshot(self):
        return {
            "job_id": str(self.id),
            "title": self.title,
            "description": self.description,
            "business_id": str(self.business.id),
            "business_name": self.business.legal_name,
            "business_verification_status": self.business.verification_status,
            "location_address": self.location_address,
            "location_city": self.location_city,
            "work_date": str(self.work_date),
            "start_time": str(self.start_time),
            "end_time": str(self.end_time),
            "num_workers_needed": self.num_workers_needed,
            "required_skills": self.required_skills,
            "wage_amount": self.wage_amount,
            "wage_currency": self.wage_currency,
            "wage_basis": self.wage_basis,
            "payment_method": self.payment_method,
            "attendance_requirements": self.attendance_requirements,
            "cancellation_policy": self.cancellation_policy,
            "additional_conditions": self.additional_conditions,
            "listing_version": self.version,
        }


# Terms a worker cares about when confirming an offer, in display order.
WORKER_FACING_TERMS = (
    "work_date", "start_time", "end_time", "location_city", "location_address",
    "wage_amount", "wage_basis", "description", "required_skills",
    "attendance_requirements", "cancellation_policy", "additional_conditions",
)


def changed_terms(before, after):
    """Keys of WORKER_FACING_TERMS that differ; [] when nothing was recorded before."""
    if not before:
        return []
    return [k for k in WORKER_FACING_TERMS if k in before and before.get(k) != after.get(k)]


class JobApplication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(JobListing, on_delete=models.PROTECT, related_name="applications")
    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="job_applications",
    )
    # The terms the worker saw when applying; the offer shows what changed since.
    terms_at_apply = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=ApplicationStatus.choices,
        default=ApplicationStatus.PENDING,
    )
    cover_note = models.TextField(blank=True)
    applied_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("job", "worker")]
        ordering = ["-applied_at"]

    def __str__(self):
        return f"{self.worker.email} → {self.job.title} ({self.status})"
