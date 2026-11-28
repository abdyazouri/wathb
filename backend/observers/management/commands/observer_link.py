from django.core.management.base import BaseCommand, CommandError

from observers.models import ObserverProfile
from observers.tokens import set_password_link


class Command(BaseCommand):
    help = "Print a new one-time set-password link (valid 48 hours) for an observer."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)

    def handle(self, *args, **o):
        try:
            profile = ObserverProfile.objects.select_related("user").get(user__email__iexact=o["email"].strip())
        except ObserverProfile.DoesNotExist as exc:
            raise CommandError(f"No observer with email {o['email']}.") from exc
        self.stdout.write("One-time set-password link (valid 48 hours; share it privately):")
        self.stdout.write(set_password_link(profile.user))
