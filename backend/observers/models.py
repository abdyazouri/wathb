"""Read-only observers: external partners, team members and (later) funders following a programme.

An observer is a User with role OBSERVER plus an ObserverProfile. What they may see is set by the
profile's level and its ObserverScope; observers never write anything (see middleware.py).
"""
import random

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone


class ObserverLevel(models.TextChoices):
    AGGREGATE = "aggregate", "Aggregate: numbers and charts only"
    PSEUDONYMISED = "pseudonymised", "Pseudonymised: «عامل #12», «منشأة #3»"
    NAMED = "named", "Named: worker and business names (no phones)"


class ObserverLanguage(models.TextChoices):
    ARABIC = "ar", "العربية"
    ENGLISH = "en", "English"


class ObserverScope(models.Model):
    """Which data an observer sees. Kept apart from the observer so a funder programme can own a
    scope later (a link on this model) without changing ObserverProfile."""

    name = models.CharField(max_length=200)
    all_businesses = models.BooleanField(default=True, help_text="Off: only the businesses chosen below.")
    businesses = models.ManyToManyField("accounts.BusinessProfile", blank=True, related_name="observer_scopes")
    start_date = models.DateField(null=True, blank=True, help_text="Nothing before this date (Gaza time).")
    end_date = models.DateField(null=True, blank=True, help_text="Nothing after this date (Gaza time).")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ObserverProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="observer_profile")
    display_name = models.CharField(max_length=200)
    organisation = models.CharField(max_length=200, help_text="e.g. «Tech for Palestine», «Wathb team».")
    level = models.CharField(max_length=20, choices=ObserverLevel.choices, default=ObserverLevel.AGGREGATE)
    language = models.CharField(max_length=2, choices=ObserverLanguage.choices, default=ObserverLanguage.ARABIC)
    scope = models.ForeignKey(ObserverScope, on_delete=models.PROTECT, related_name="observers")
    expires_at = models.DateField(help_text="Last day the account works (Gaza time).")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.display_name} ({self.organisation})"

    @property
    def is_usable(self):
        """Active and not past its expiry date. Anything else is signed out and blocked."""
        return bool(self.user.is_active and timezone.localdate() <= self.expires_at)


class PseudonymKind(models.TextChoices):
    WORKER = "WORKER", "Worker"
    BUSINESS = "BUSINESS", "Business"


class Pseudonym(models.Model):
    """A random number per worker or business, assigned once and shown to every observer
    («عامل #12»). Never derived from internal IDs."""

    kind = models.CharField(max_length=10, choices=PseudonymKind.choices)
    object_id = models.CharField(max_length=64)
    number = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "object_id"], name="one_pseudonym_per_entity"),
            models.UniqueConstraint(fields=["kind", "number"], name="unique_pseudonym_number"),
        ]

    def __str__(self):
        return f"{self.kind} #{self.number}"

    @classmethod
    def number_for(cls, kind, object_id):
        object_id = str(object_id)
        existing = cls.objects.filter(kind=kind, object_id=object_id).values_list("number", flat=True).first()
        if existing is not None:
            return existing
        for _ in range(50):
            # Room grows with the table so collisions stay rare; numbers never reveal order.
            ceiling = max(999, cls.objects.filter(kind=kind).count() * 10)
            try:
                with transaction.atomic():
                    return cls.objects.create(kind=kind, object_id=object_id,
                                              number=random.randint(1, ceiling)).number
            except IntegrityError:
                found = cls.objects.filter(kind=kind, object_id=object_id).values_list("number", flat=True).first()
                if found is not None:  # another request assigned it meanwhile
                    return found
        raise RuntimeError("Could not assign a pseudonym number.")
