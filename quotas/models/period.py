from django.db import models
from django.db.models import F, Q


class Period(models.Model):
    name = models.CharField(max_length=100)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    class Meta:
        ordering = ["start_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_at__gt=F("start_at")),
                name="period_end_after_start",
            ),
        ]

    def __str__(self):
        return self.name
