"""Close offers left OFFERED after their application was rejected or withdrawn.

Before the «سحب العرض» fix, rejecting an offered application left its assignment
OFFERED. Rejected or cancelled → CANCELLED (with a reason), withdrawn → DECLINED.
"""
from django.db import migrations
from django.utils import timezone

WITHDRAWN_OFFER_REASON = "سحب صاحب العمل العرض."


def close_withdrawn_offers(apps, schema_editor):
    Assignment = apps.get_model("assignments", "Assignment")
    stale = Assignment.objects.filter(status="OFFERED", application__isnull=False).exclude(application__status="OFFERED")
    stale.filter(application__status="WITHDRAWN").update(status="DECLINED")
    stale.update(status="CANCELLED", cancelled_at=timezone.now(), cancellation_reason=WITHDRAWN_OFFER_REASON)


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0002_arabic_choice_labels"),
        ("jobs", "0009_alter_joblisting_payment_method"),
    ]

    operations = [
        migrations.RunPython(close_withdrawn_offers, migrations.RunPython.noop),
    ]
