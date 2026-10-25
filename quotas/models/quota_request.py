from django.conf import settings
from django.db import models
from django.db.models import Q

from .period import Period
from .quota import QUOTA_CEILING_MINUTES


class RequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class QuotaRequest(models.Model):
    Status = RequestStatus

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="quota_requests",
    )
    period = models.ForeignKey(Period, on_delete=models.PROTECT, related_name="requests")
    minutes = models.PositiveSmallIntegerField()
    reason = models.TextField()
    status = models.CharField(
        max_length=16,
        choices=RequestStatus.choices,
        default=RequestStatus.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["-created_at", "-id"], name="request_created_id_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(minutes__gte=1) & Q(minutes__lte=QUOTA_CEILING_MINUTES),
                name="request_minutes_in_range",
            ),
            models.CheckConstraint(
                condition=Q(status__in=RequestStatus.values),
                name="request_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status=RequestStatus.PENDING, decided_at__isnull=True)
                    | (~Q(status=RequestStatus.PENDING) & Q(decided_at__isnull=False))
                ),
                name="request_decided_at_matches_status",
            ),
        ]

    @property
    def is_terminal(self):
        return self.status != RequestStatus.PENDING
