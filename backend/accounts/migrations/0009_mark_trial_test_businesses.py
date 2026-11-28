"""Mark the three test businesses created before the trial (confirmed by the product owner: IDs 1, 2, 3).

Matches those IDs only; the «[تجريبي]» name prefix is a guard so a database where these IDs are real
businesses (a fresh or local database) is never touched.
"""
from django.db import migrations

TEST_BUSINESS_IDS = [1, 2, 3]


def mark(apps, schema_editor):
    BusinessProfile = apps.get_model("accounts", "BusinessProfile")
    BusinessProfile.objects.filter(pk__in=TEST_BUSINESS_IDS, legal_name__startswith="[تجريبي]").update(is_test=True)


def unmark(apps, schema_editor):
    BusinessProfile = apps.get_model("accounts", "BusinessProfile")
    BusinessProfile.objects.filter(pk__in=TEST_BUSINESS_IDS).update(is_test=False)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0008_businessprofile_is_test")]
    operations = [migrations.RunPython(mark, unmark)]
