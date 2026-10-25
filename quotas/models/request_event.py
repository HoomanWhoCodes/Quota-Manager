from django.conf import settings
from django.db import models
from django.db.models import Q

from .quota_request import QuotaRequest


class EventType(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    DECISION_RECORDED = "decision_recorded", "Decision recorded"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


FINAL_EVENT_TYPES = [EventType.APPROVED, EventType.REJECTED]


class RequestEvent(models.Model):
    Type = EventType

    request = models.ForeignKey(QuotaRequest, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(event_type__in=EventType.values),
                name="event_type_valid",
            ),
            models.UniqueConstraint(
                fields=["request"],
                condition=Q(event_type__in=FINAL_EVENT_TYPES),
                name="event_single_final_per_request",
            ),
        ]
