from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand

from utils.models import IdempotencyKey
from utils import clock


class Command(BaseCommand):
    help = "Delete idempotency keys older than IDEMPOTENCY_KEY_TTL_HOURS."

    def handle(self, *args, **options):
        cutoff = clock.now() - timedelta(hours=settings.IDEMPOTENCY_KEY_TTL_HOURS)
        deleted, _ = IdempotencyKey.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(f"Deleted {deleted} expired idempotency keys.")
