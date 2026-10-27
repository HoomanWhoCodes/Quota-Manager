from datetime import timedelta

import pytest

from quotas import services
from quotas.exceptions import Forbidden, InvalidState, NotFound, QuotaExceeded
from quotas.models import Decision, EventType, Quota, RequestEvent
from utils.testing.api import decide, detail_url, error_code, quota_url


def consumed(employee, period):
    quota = Quota.objects.filter(employee=employee, period=period).first()
    return quota.consumed_minutes if quota else 0


def final_events(request):
    return RequestEvent.objects.filter(
        request=request, event_type__in=[EventType.APPROVED, EventType.REJECTED]
    )


@pytest.mark.django_db
class TestDecisionTable:
    """One test per row of the decision table in the task."""

    def test_rejection_finishes_the_request(self, client_for, make_request, employee, manager, period):
        request = make_request(employee, minutes=120)

        response = decide(client_for(manager), request.id, "reject")

        assert response.status_code == 200
        assert response.json()["request"]["status"] == "rejected"
        assert response.json()["decision"]["outcome"] == "reject"
        request.refresh_from_db()
        assert request.status == "rejected"
        assert request.decided_at is not None
        assert consumed(employee, period) == 0
        assert [e.event_type for e in final_events(request)] == [EventType.REJECTED]

    def test_hr_can_reject_alone_too(self, client_for, make_request, employee, hr):
        request = make_request(employee)

        response = decide(client_for(hr), request.id, "reject")

        assert response.json()["request"]["status"] == "rejected"

    def test_first_approval_keeps_request_pending(self, client_for, make_request, employee, manager, period):
        request = make_request(employee, minutes=120)

        response = decide(client_for(manager), request.id, "approve")

        assert response.status_code == 200
        assert response.json()["request"]["status"] == "pending"
        assert Decision.objects.filter(request=request).count() == 1
        assert consumed(employee, period) == 0
        assert not final_events(request).exists()

    @pytest.mark.parametrize("order", [("manager", "hr"), ("hr", "manager")])
    def test_second_approval_approves_and_consumes(
        self, request, client_for, make_request, employee, period, order
    ):
        quota_request = make_request(employee, minutes=120)
        first, second = (client_for(request.getfixturevalue(role)) for role in order)

        decide(first, quota_request.id, "approve")
        response = decide(second, quota_request.id, "approve")

        assert response.status_code == 200
        assert response.json()["request"]["status"] == "approved"
        quota_request.refresh_from_db()
        assert quota_request.status == "approved"
        assert consumed(employee, period) == 120
        assert [e.event_type for e in final_events(quota_request)] == [EventType.APPROVED]

    def test_second_approval_without_enough_quota(self, client_for, make_request, employee, manager, hr, period):
        big = make_request(employee, minutes=400)
        decide(client_for(manager), big.id, "approve")
        decide(client_for(hr), big.id, "approve")
        request = make_request(employee, minutes=100)
        decide(client_for(manager), request.id, "approve")

        response = decide(client_for(hr), request.id, "approve")

        assert response.status_code == 409
        assert error_code(response) == "quota_exceeded"
        request.refresh_from_db()
        assert request.status == "pending"
        assert consumed(employee, period) == 400
        # The HR decision was not saved, but the manager's approval is still there.
        assert list(request.decisions.values_list("role", "outcome")) == [("manager", "approve")]
        assert not final_events(request).exists()

    def test_quota_can_be_used_up_exactly(self, client_for, make_request, employee, manager, hr, period):
        for minutes in (300, 180):
            request = make_request(employee, minutes=minutes)
            decide(client_for(manager), request.id, "approve")
            assert decide(client_for(hr), request.id, "approve").status_code == 200

        assert consumed(employee, period) == 480

    def test_applicant_reviewing_own_request_gets_403(self, client_for, make_request, employee):
        request = make_request(employee)

        response = decide(client_for(employee), request.id, "approve")

        assert response.status_code == 403
        assert error_code(response) == "forbidden"
        assert not Decision.objects.exists()

    @pytest.mark.parametrize("who", ["other_manager", "other_employee"])
    def test_no_access_returns_404(self, request, client_for, make_request, employee, who):
        quota_request = make_request(employee)
        client = client_for(request.getfixturevalue(who))

        hidden = decide(client, quota_request.id, "approve")
        missing = decide(client, 999999, "approve")

        assert hidden.status_code == missing.status_code == 404
        assert hidden.json() == missing.json()
        assert not Decision.objects.exists()

    def test_same_role_deciding_again_returns_409(self, client_for, make_request, make_user, employee, manager, team):
        request = make_request(employee)
        decide(client_for(manager), request.id, "approve")
        # Even another manager of the same team cannot add a second manager decision.
        second_manager = make_user("max", role="manager", team=team)

        response = decide(client_for(second_manager), request.id, "reject")

        assert response.status_code == 409
        assert error_code(response) == "invalid_state"
        assert Decision.objects.filter(request=request).count() == 1

    @pytest.mark.parametrize("final", ["approve", "reject"])
    def test_finished_request_returns_409(self, client_for, make_request, employee, manager, hr, final):
        request = make_request(employee)
        if final == "approve":
            decide(client_for(manager), request.id, "approve")
            decide(client_for(hr), request.id, "approve")
        else:
            decide(client_for(hr), request.id, "reject")

        response = decide(client_for(manager), request.id, "reject")

        assert response.status_code == 409
        assert error_code(response) == "invalid_state"

    def test_invalid_decision_value_returns_400(self, client_for, make_request, employee, manager):
        request = make_request(employee)

        response = decide(client_for(manager), request.id, "maybe")

        assert response.status_code == 400
        assert error_code(response) == "validation_error"

    def test_decision_shows_up_on_the_request(self, client_for, make_request, employee, manager):
        request = make_request(employee)
        decide(client_for(manager), request.id, "approve")

        body = client_for(employee).get(detail_url(request.id)).json()

        assert body["decisions"][0]["role"] == "manager"
        assert body["decisions"][0]["outcome"] == "approve"


@pytest.mark.django_db
class TestEventLog:
    def test_every_change_is_logged_with_actor(self, client_for, make_request, employee, manager, hr):
        request = make_request(employee)
        decide(client_for(manager), request.id, "approve")
        decide(client_for(hr), request.id, "approve")

        events = list(request.events.values_list("event_type", "actor_id"))

        assert events == [
            ("submitted", employee.id),
            ("decision_recorded", manager.id),
            ("decision_recorded", hr.id),
            ("approved", hr.id),
        ]
        assert all(e.created_at for e in request.events.all())

    def test_failed_attempts_are_not_logged(self, client_for, make_request, employee, other_manager):
        request = make_request(employee)

        decide(client_for(other_manager), request.id, "approve")  # 404
        decide(client_for(employee), request.id, "approve")  # 403

        assert list(request.events.values_list("event_type", flat=True)) == ["submitted"]


@pytest.mark.django_db
class TestClockAndPeriodEnd:
    def test_decision_after_period_end_is_allowed(
        self, client_for, make_request, employee, manager, hr, period, frozen_clock
    ):
        request = make_request(employee, minutes=60)
        frozen_clock.current = period.end_at + timedelta(days=3)

        decide(client_for(manager), request.id, "approve")
        response = decide(client_for(hr), request.id, "approve")

        assert response.status_code == 200
        assert response.json()["request"]["status"] == "approved"
        assert consumed(employee, period) == 60

    def test_decided_at_comes_from_the_app_clock(self, make_request, employee, hr, frozen_clock):
        request = make_request(employee)

        services.decide(actor=hr, request_id=request.id, outcome="reject")

        request.refresh_from_db()
        assert request.decided_at == frozen_clock.current


@pytest.mark.django_db
class TestServiceWithoutHttp:
    """The domain rules live in services, so they hold even without the API."""

    def test_full_approval(self, make_request, employee, manager, hr, period):
        request = make_request(employee, minutes=200)

        services.decide(actor=manager, request_id=request.id, outcome="approve")
        decision = services.decide(actor=hr, request_id=request.id, outcome="approve")

        assert decision.request.status == "approved"
        assert consumed(employee, period) == 200

    def test_errors_are_domain_exceptions(self, make_request, employee, other_employee, manager, other_manager, hr):
        request = make_request(employee, minutes=480)
        other = make_request(employee, minutes=1)

        with pytest.raises(Forbidden):
            services.decide(actor=employee, request_id=request.id, outcome="approve")
        with pytest.raises(NotFound):
            services.decide(actor=other_manager, request_id=request.id, outcome="approve")
        with pytest.raises(NotFound):
            services.decide(actor=other_employee, request_id=request.id, outcome="approve")

        services.decide(actor=manager, request_id=request.id, outcome="approve")
        with pytest.raises(InvalidState):
            services.decide(actor=manager, request_id=request.id, outcome="approve")
        services.decide(actor=hr, request_id=request.id, outcome="approve")

        services.decide(actor=manager, request_id=other.id, outcome="approve")
        with pytest.raises(QuotaExceeded):
            services.decide(actor=hr, request_id=other.id, outcome="approve")


@pytest.mark.django_db
class TestQuotaSummary:
    def test_fresh_quota(self, client_for, employee, period):
        response = client_for(employee).get(quota_url(period.id))

        assert response.status_code == 200
        assert response.json() == {
            "period_id": period.id,
            "ceiling_minutes": 480,
            "consumed_minutes": 0,
            "remaining_minutes": 480,
        }

    def test_after_approval(self, client_for, make_request, employee, manager, hr, period):
        request = make_request(employee, minutes=150)
        decide(client_for(manager), request.id, "approve")
        decide(client_for(hr), request.id, "approve")

        body = client_for(employee).get(quota_url(period.id)).json()

        assert (body["consumed_minutes"], body["remaining_minutes"]) == (150, 330)

    def test_pending_requests_do_not_reserve_quota(self, client_for, make_request, employee, period):
        make_request(employee, minutes=300)

        body = client_for(employee).get(quota_url(period.id)).json()

        assert body["remaining_minutes"] == 480

    def test_always_shows_the_callers_own_quota(self, client_for, make_request, employee, other_employee, manager, hr, period):
        request = make_request(employee, minutes=150)
        decide(client_for(manager), request.id, "approve")
        decide(client_for(hr), request.id, "approve")

        # There is no way to ask for someone else's quota; extra params are ignored.
        body = client_for(other_employee).get(quota_url(period.id), {"employee_id": employee.id}).json()

        assert body["consumed_minutes"] == 0

    def test_unknown_period_returns_404(self, client_for, employee):
        response = client_for(employee).get(quota_url(999999))

        assert response.status_code == 404
        assert error_code(response) == "not_found"
