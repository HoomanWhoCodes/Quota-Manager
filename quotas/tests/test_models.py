"""The database itself must block broken data, even if the service layer has a bug."""

from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from quotas.models import Decision, EventType, Period, Quota, QuotaRequest, RequestEvent, RequestStatus


@pytest.mark.django_db
class TestQuotaConstraints:
    def test_consumed_cannot_go_over_480(self, employee, period):
        with pytest.raises(IntegrityError):
            Quota.objects.create(employee=employee, period=period, consumed_minutes=481)

    def test_consumed_can_be_exactly_480(self, employee, period):
        quota = Quota.objects.create(employee=employee, period=period, consumed_minutes=480)
        assert quota.remaining_minutes == 0

    def test_one_quota_row_per_employee_and_period(self, employee, period):
        Quota.objects.create(employee=employee, period=period)
        with pytest.raises(IntegrityError):
            Quota.objects.create(employee=employee, period=period)


@pytest.mark.django_db
class TestRequestConstraints:
    @pytest.mark.parametrize("minutes", [0, 481])
    def test_minutes_must_be_between_1_and_480(self, employee, period, minutes):
        with pytest.raises(IntegrityError):
            QuotaRequest.objects.create(employee=employee, period=period, minutes=minutes, reason="x")

    def test_finished_request_needs_decided_at(self, make_request, employee):
        request = make_request(employee)
        request.status = RequestStatus.APPROVED
        with pytest.raises(IntegrityError):
            request.save()

    def test_pending_request_cannot_have_decided_at(self, make_request, employee):
        request = make_request(employee)
        request.decided_at = timezone.now()
        with pytest.raises(IntegrityError):
            request.save()


@pytest.mark.django_db
class TestDecisionConstraints:
    def test_one_decision_per_role(self, make_request, employee, manager, other_manager):
        request = make_request(employee)
        Decision.objects.create(request=request, role="manager", actor=manager, outcome="approve")
        with pytest.raises(IntegrityError):
            Decision.objects.create(request=request, role="manager", actor=other_manager, outcome="reject")

    def test_manager_and_hr_can_both_decide(self, make_request, employee, manager, hr):
        request = make_request(employee)
        Decision.objects.create(request=request, role="manager", actor=manager, outcome="approve")
        Decision.objects.create(request=request, role="hr", actor=hr, outcome="approve")
        assert request.decisions.count() == 2


@pytest.mark.django_db
class TestEventConstraints:
    def test_at_most_one_final_event_per_request(self, make_request, employee, hr):
        request = make_request(employee)
        RequestEvent.objects.create(request=request, actor=hr, event_type=EventType.APPROVED)
        with pytest.raises(IntegrityError):
            RequestEvent.objects.create(request=request, actor=hr, event_type=EventType.REJECTED)

    def test_many_non_final_events_are_fine(self, make_request, employee, manager, hr):
        request = make_request(employee)
        RequestEvent.objects.create(request=request, actor=manager, event_type=EventType.DECISION_RECORDED)
        RequestEvent.objects.create(request=request, actor=hr, event_type=EventType.DECISION_RECORDED)
        # One "submitted" event plus the two above.
        assert request.events.count() == 3


@pytest.mark.django_db
def test_period_must_end_after_it_starts():
    now = timezone.now()
    with pytest.raises(IntegrityError):
        Period.objects.create(name="Bad", start_at=now, end_at=now - timedelta(days=1))
