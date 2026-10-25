from django.db import transaction

from quotas.exceptions import Forbidden, InvalidInput
from quotas.models import EventType, Period, QuotaRequest, RequestEvent
from utils import clock

from .access import visible_requests


def submit_request(*, employee, period_id, minutes, reason):
    if not employee.is_employee:
        raise Forbidden("Only employees can submit requests.")

    period = Period.objects.filter(pk=period_id).first()
    if period is None:
        raise InvalidInput(details={"period_id": "Period does not exist."})
    if clock.now() >= period.end_at:
        raise InvalidInput(details={"period_id": "This period has already ended."})

    with transaction.atomic():
        request = QuotaRequest.objects.create(
            employee=employee,
            period=period,
            minutes=minutes,
            reason=reason,
        )
        RequestEvent.objects.create(request=request, actor=employee, event_type=EventType.SUBMITTED)
    return request


def list_requests(*, user, status=None, period_id=None):
    qs = visible_requests(user).select_related("employee", "period").prefetch_related("decisions")
    if status:
        qs = qs.filter(status=status)
    if period_id:
        qs = qs.filter(period_id=period_id)
    return qs.order_by("-created_at", "-id")
