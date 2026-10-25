from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q

from .team import Team


class User(AbstractUser):
    class Role(models.TextChoices):
        EMPLOYEE = "employee", "Employee"
        MANAGER = "manager", "Manager"
        HR = "hr", "HR"


    role = models.CharField(max_length=16, choices=Role.choices, default=Role.EMPLOYEE)
    team = models.ForeignKey(
        Team,
        on_delete=models.PROTECT,
        related_name="members",
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(role__in=["employee", "manager", "hr"]),
                name="user_role_valid",
            ),
            models.CheckConstraint(
                condition=Q(role="hr") | Q(team__isnull=False),
                name="user_team_required_unless_hr",
            ),
        ]

    @property
    def is_employee(self):
        return self.role == self.Role.EMPLOYEE

    @property
    def is_manager(self):
        return self.role == self.Role.MANAGER

    @property
    def is_hr(self):
        return self.role == self.Role.HR
