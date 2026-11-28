"""Two test jobs stayed FILLED after their tasks were cancelled and their test business was deleted
(the bug fixed by JobListing.refresh_fill_status). Their business is gone, so they are cancelled, not reopened.

Matches these two IDs only, and only while still FILLED with no task holding a place.
"""
import uuid

from django.db import migrations

JOB_IDS = [uuid.UUID("aaff6a7f-ed00-46ad-8e9f-62cef06ffd86"), uuid.UUID("b7db8ed9-bf53-46b3-ab0e-ddeb84d7c8ba")]
REASON = "أُلغيت مهامها وحُذف حساب المنشأة التجريبية."


def cancel(apps, schema_editor):
    JobListing = apps.get_model("jobs", "JobListing")
    Assignment = apps.get_model("assignments", "Assignment")
    for job in JobListing.objects.filter(pk__in=JOB_IDS, status="FILLED"):
        if not Assignment.objects.filter(job=job, status__in=["ACCEPTED", "ACTIVE", "COMPLETED"]).exists():
            job.status = "CANCELLED"
            job.cancellation_reason = REASON
            job.save(update_fields=["status", "cancellation_reason"])


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0009_alter_joblisting_payment_method"),
        ("assignments", "0003_close_withdrawn_offers"),
    ]
    operations = [migrations.RunPython(cancel, migrations.RunPython.noop)]
