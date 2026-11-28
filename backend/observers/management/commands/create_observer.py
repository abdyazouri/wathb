import datetime

from django.core.management.base import BaseCommand, CommandError

from observers.models import ObserverLanguage, ObserverLevel
from observers.services import create_observer


def _date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(f"Not a date (YYYY-MM-DD): {value}") from exc


class Command(BaseCommand):
    help = "Create a read-only observer and print a one-time set-password link (valid 48 hours). Never prints a password."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True)
        parser.add_argument("--org", required=True, help='e.g. "Tech for Palestine"')
        parser.add_argument("--email", required=True, help="The observer signs in with this email.")
        parser.add_argument("--level", required=True, choices=ObserverLevel.values)
        parser.add_argument("--lang", default="ar", choices=ObserverLanguage.values)
        parser.add_argument("--expires", required=True, type=_date, help="Last day the account works, YYYY-MM-DD.")
        parser.add_argument("--businesses", default="", help="Comma-separated business profile IDs (default: all).")
        parser.add_argument("--from", dest="start", type=_date, help="Scope start date, YYYY-MM-DD.")
        parser.add_argument("--to", dest="end", type=_date, help="Scope end date, YYYY-MM-DD.")

    def handle(self, *args, **o):
        ids = [int(x) for x in o["businesses"].split(",") if x.strip()]
        try:
            profile, link = create_observer(
                name=o["name"], organisation=o["org"], email=o["email"], level=o["level"], language=o["lang"],
                expires_at=o["expires"], business_ids=ids or None, start_date=o["start"], end_date=o["end"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Created observer {profile.display_name} <{profile.user.email}> "
                          f"({profile.level}, {profile.language}, until {profile.expires_at}).")
        self.stdout.write("One-time set-password link (valid 48 hours; share it privately):")
        self.stdout.write(link)
