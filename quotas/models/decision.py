from django.conf import settings
from django.db import models
from django.db.models import Q

from .quota_request import QuotaRequest


class ReviewerRole(models.TextChoices):
    MANAGER = "manager", "Manager"
    HR = "hr", "HR"


class DecisionOutcome(models.TextChoices):
    APPROVE = "approve", "Approve"
    REJECT = "reject", "Reject"


class Decision(models.Model):
    request = models.ForeignKey(QuotaRequest, on_delete=models.PROTECT, related_name="decisions")
    role = models.CharField(max_length=16, choices=ReviewerRole.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="decisions",
    )
    outcome = models.CharField(max_length=16, choices=DecisionOutcome.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["request", "role"],
                name="decision_unique_request_role",
            ),
            models.CheckConstraint(
                condition=Q(role__in=ReviewerRole.values),
                name="decision_role_valid",
            ),
            models.CheckConstraint(
                condition=Q(outcome__in=DecisionOutcome.values),
                name="decision_outcome_valid",
            ),
        ]
