import uuid
from django.db import models
from django.conf import settings
from jobs.models import Currency


class FundingProposalStatus(models.TextChoices):
    PROPOSED = "PROPOSED", "مقترَح"
    PLEDGED = "PLEDGED", "تم التعهّد"
    APPROVED = "APPROVED", "معتمَد"
    ACTIVE = "ACTIVE", "نشط"
    COMPLETED = "COMPLETED", "مكتمل"
    CANCELLED = "CANCELLED", "ملغى"


class FundingAllocationStatus(models.TextChoices):
    RESERVED = "RESERVED", "محجوز"
    ALLOCATED = "ALLOCATED", "مخصَّص"
    RELEASED = "RELEASED", "مُحرَّر"
    SPENT = "SPENT", "مصروف"


class FundingProposal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    funder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="funding_proposals",
    )
    title = models.CharField(max_length=300)
    description = models.TextField()
    total_amount = models.PositiveBigIntegerField(help_text="Amount in minor currency units")
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.ILS)
    status = models.CharField(
        max_length=20,
        choices=FundingProposalStatus.choices,
        default=FundingProposalStatus.PROPOSED,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_proposals",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Proposal: {self.title} ({self.status})"


class FundingBudget(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    proposal = models.OneToOneField(FundingProposal, on_delete=models.PROTECT, related_name="budget")
    total_amount = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, choices=Currency.choices)
    reserved_amount = models.PositiveBigIntegerField(default=0)
    allocated_amount = models.PositiveBigIntegerField(default=0)
    spent_amount = models.PositiveBigIntegerField(default=0)

    @property
    def available_amount(self):
        return self.total_amount - self.reserved_amount - self.allocated_amount - self.spent_amount

    def __str__(self):
        return f"Budget for {self.proposal.title}: {self.total_amount} {self.currency}"


class FundingAllocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    budget = models.ForeignKey(FundingBudget, on_delete=models.PROTECT, related_name="allocations")
    job_listing = models.OneToOneField(
        "jobs.JobListing",
        on_delete=models.PROTECT,
        related_name="funding_allocation",
    )
    amount = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, choices=Currency.choices)
    status = models.CharField(
        max_length=20,
        choices=FundingAllocationStatus.choices,
        default=FundingAllocationStatus.RESERVED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Allocation {self.amount} {self.currency} for {self.job_listing} ({self.status})"
