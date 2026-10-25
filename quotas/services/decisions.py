from django.db import transaction

from quotas.exceptions import Forbidden, InvalidState, NotFound, QuotaExceeded
from quotas.models import (
    QUOTA_CEILING_MINUTES,
    Decision,
    DecisionOutcome,
    EventType,
    Quota,
    RequestEvent,
    RequestStatus,
    ReviewerRole,
)
from utils import clock

from .access import visible_requests


def decide(*, actor, request_id, outcome):
    with transaction.atomic():
        # Lock order is always: request row first, then quota row.
        # Every decision on the same request waits here, so they run one by one.
        request = (
            visible_requests(actor)
            .select_for_update(of=("self",))
            .filter(pk=request_id)
            .first()
        )
        if request is None:
            raise NotFound()
        if request.employee_id == actor.id:
            raise Forbidden("You cannot review your own request.")

        # Someone who is not a reviewer gets 404, so they learn nothing
        # about whether the request exists.
        role = _reviewer_role(actor)
        if role is None:
            raise NotFound()

        if request.status != RequestStatus.PENDING:
            raise InvalidState("This request is already finished.")
        if Decision.objects.filter(request=request, role=role).exists():
            raise InvalidState("Your role has already decided on this request.")

        now = clock.now()

        if outcome == DecisionOutcome.REJECT:
            decision = _record_decision(request, role, actor, outcome)
            _finish(request, RequestStatus.REJECTED, EventType.REJECTED, actor, now)
            return decision

        other_role = ReviewerRole.HR if role == ReviewerRole.MANAGER else ReviewerRole.MANAGER
        other_approved = Decision.objects.filter(
            request=request, role=other_role, outcome=DecisionOutcome.APPROVE
        ).exists()

        if not other_approved:
            return _record_decision(request, role, actor, outcome)

        quota = _lock_quota(request)
        if quota.consumed_minutes + request.minutes > QUOTA_CEILING_MINUTES:
            # Nothing has been written yet, so leaving here keeps the request
            # PENDING and the first approval stays as it was.
            raise QuotaExceeded()

        quota.consumed_minutes += request.minutes
        quota.save(update_fields=["consumed_minutes", "updated_at"])

        decision = _record_decision(request, role, actor, outcome)
        _finish(request, RequestStatus.APPROVED, EventType.APPROVED, actor, now)
        return decision


def _reviewer_role(user):
    if user.is_manager:
        return ReviewerRole.MANAGER
    if user.is_hr:
        return ReviewerRole.HR
    return None


def _record_decision(request, role, actor, outcome):
    decision = Decision.objects.create(request=request, role=role, actor=actor, outcome=outcome)
    RequestEvent.objects.create(request=request, actor=actor, event_type=EventType.DECISION_RECORDED)
    return decision


def _finish(request, status, event_type, actor, now):
    request.status = status
    request.decided_at = now
    request.save(update_fields=["status", "decided_at", "updated_at"])
    RequestEvent.objects.create(request=request, actor=actor, event_type=event_type)


def _lock_quota(request):
    # Create the row if it is missing. ON CONFLICT DO NOTHING means two
    # transactions doing this at once cannot create two rows or crash.
    Quota.objects.bulk_create(
        [Quota(employee_id=request.employee_id, period_id=request.period_id)],
        ignore_conflicts=True,
    )
    return Quota.objects.select_for_update().get(
        employee_id=request.employee_id, period_id=request.period_id
    )
