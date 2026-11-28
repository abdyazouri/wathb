from django.core.management.base import BaseCommand, CommandError

from observers.models import ObserverLanguage, ObserverLevel, ObserverProfile
from observers.management.commands.create_observer import _date


class Command(BaseCommand):
    help = "Extend, deactivate, activate or change an observer (by email)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--extend", type=_date, help="New last day, YYYY-MM-DD.")
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--deactivate", action="store_true", help="Blocks and signs out the observer.")
        group.add_argument("--activate", action="store_true")
        parser.add_argument("--level", choices=ObserverLevel.values)
        parser.add_argument("--lang", choices=ObserverLanguage.values)

    def handle(self, *args, **o):
        try:
            profile = ObserverProfile.objects.select_related("user").get(user__email__iexact=o["email"].strip())
        except ObserverProfile.DoesNotExist as exc:
            raise CommandError(f"No observer with email {o['email']}.") from exc
        changes = []
        if o["extend"]:
            profile.expires_at = o["extend"]
            changes.append(f"expires {o['extend']}")
        if o["level"]:
            profile.level = o["level"]
            changes.append(f"level {o['level']}")
        if o["lang"]:
            profile.language = o["lang"]
            changes.append(f"language {o['lang']}")
        profile.save()
        if o["deactivate"] or o["activate"]:
            profile.user.is_active = bool(o["activate"])
            profile.user.save(update_fields=["is_active"])
            changes.append("activated" if o["activate"] else "deactivated")
        self.stdout.write(f"{profile.display_name}: " + (", ".join(changes) or "no change"))
