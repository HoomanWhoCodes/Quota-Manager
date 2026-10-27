from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework.authtoken.models import Token

from accounts.models import Team, User
from quotas.models import Decision, Period, Quota, QuotaRequest, RequestEvent
from utils.models import IdempotencyKey
from utils import clock

# All passwords and tokens here are fake and only for local testing.
PASSWORD = "password123"
PERIOD_DAYS = 30

USERS = [
    {"username": "alice", "role": User.Role.EMPLOYEE, "team": "Engineering"},
    {"username": "bob", "role": User.Role.EMPLOYEE, "team": "Engineering"},
    {"username": "maria", "role": User.Role.MANAGER, "team": "Engineering"},
    {"username": "sam", "role": User.Role.MANAGER, "team": "Sales"},
    {"username": "hana", "role": User.Role.HR, "team": None},
    # Superuser for the Django admin. It needs a role, and HR is the one without a team.
    {"username": "admin", "role": User.Role.HR, "team": None, "superuser": True},
]


class Command(BaseCommand):
    help = "Create sample data: an open period, teams, users and fake API tokens."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when DEBUG is off.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="First delete all requests, decisions, events, quotas, idempotency keys and rate limits.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError("Seed data has fake passwords. Use --force to run it with DEBUG off.")

        with transaction.atomic():
            if options["reset"]:
                self._reset()
            period = self._open_period()
            users = [self._user(**data) for data in USERS]

        self.stdout.write(self.style.SUCCESS(f"Period #{period.id}: {period.start_at} -> {period.end_at}"))
        self.stdout.write(f"Password for every user: {PASSWORD}\n")
        self.stdout.write(f"{'user':<8} {'role':<9} {'team':<12} token")
        for user in users:
            team = user.team.name if user.team else "-"
            self.stdout.write(f"{user.username:<8} {user.role:<9} {team:<12} {user.auth_token.key}")

    def _reset(self):
        # Children first, because the foreign keys are PROTECT.
        for model in [RequestEvent, Decision, Quota, QuotaRequest, IdempotencyKey]:
            model.objects.all().delete()
        cache.clear()  # rate limit counters
        self.stdout.write(self.style.WARNING("Deleted all requests, quotas and idempotency keys."))

    def _open_period(self):
        # Reuse a period that is still open, so running seed twice is safe.
        # If the old one has ended, make a new one that starts today.
        now = clock.now()
        period = Period.objects.filter(start_at__lte=now, end_at__gt=now).order_by("-end_at").first()
        if period:
            return period

        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=PERIOD_DAYS)
        return Period.objects.create(name=f"{start:%Y-%m-%d} to {end:%Y-%m-%d}", start_at=start, end_at=end)

    def _user(self, username, role, team, superuser=False):
        team_obj = Team.objects.get_or_create(name=team)[0] if team else None
        user, _ = User.objects.update_or_create(
            username=username,
            defaults={"role": role, "team": team_obj, "is_staff": superuser, "is_superuser": superuser},
        )
        user.set_password(PASSWORD)
        user.save(update_fields=["password"])

        Token.objects.filter(user=user).delete()
        Token.objects.create(user=user, key=f"{username}-fake-token")
        return user
