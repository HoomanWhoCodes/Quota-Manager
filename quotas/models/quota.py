from django.conf import settings
from django.db import models
from django.db.models import Q

from .period import Period

QUOTA_CEILING_MINUTES = 480


class Quota(models.Model):
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="quotas",
    )
    period = models.ForeignKey(Period, on_delete=models.PROTECT, related_name="quotas")
    consumed_minutes = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "period"],
                name="quota_unique_employee_period",
            ),
            models.CheckConstraint(
                condition=Q(consumed_minutes__gte=0)
                & Q(consumed_minutes__lte=QUOTA_CEILING_MINUTES),
                name="quota_consumed_within_ceiling",
            ),
        ]

    @property
    def remaining_minutes(self):
        return QUOTA_CEILING_MINUTES - self.consumed_minutes
