from datetime import timedelta

import pytest
from django.utils import timezone

from quotas.models import EventType, Period, QuotaRequest, RequestEvent
from utils.testing.api import REQUESTS_URL, detail_url, error_code, submit


@pytest.mark.django_db
class TestSubmit:
    def test_employee_creates_pending_request(self, client_for, employee, period):
        response = submit(client_for(employee), period.id, minutes=90, reason="Dentist")

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"
        assert body["minutes"] == 90
        assert body["employee_id"] == employee.id
        assert body["decisions"] == []

    def test_submit_writes_a_submitted_event(self, client_for, employee, period):
        request_id = submit(client_for(employee), period.id).json()["id"]

        event = RequestEvent.objects.get(request_id=request_id)
        assert (event.event_type, event.actor_id) == (EventType.SUBMITTED, employee.id)

    def test_submit_does_not_check_remaining_quota(self, client_for, employee, period):
        client = client_for(employee)
        for _ in range(3):
            assert submit(client, period.id, minutes=480).status_code == 201

    @pytest.mark.parametrize(
        "data",
        [
            {"minutes": 0},
            {"minutes": 481},
            {"minutes": -5},
            {"minutes": "abc"},
            {"reason": ""},
        ],
    )
    def test_invalid_input_returns_400(self, client_for, employee, period, data):
        payload = {"period_id": period.id, "minutes": 60, "reason": "x", **data}
        response = client_for(employee).post(
            REQUESTS_URL, payload, format="json", headers={"Idempotency-Key": "k"}
        )

        assert response.status_code == 400
        assert error_code(response) == "validation_error"
        assert not QuotaRequest.objects.exists()

    def test_missing_fields_are_listed_in_details(self, client_for, employee):
        response = client_for(employee).post(
            REQUESTS_URL, {}, format="json", headers={"Idempotency-Key": "k"}
        )

        assert response.status_code == 400
        assert set(response.json()["error"]["details"]) == {"period_id", "minutes", "reason"}

    def test_unknown_period_returns_400(self, client_for, employee):
        response = submit(client_for(employee), period_id=999999)

        assert response.status_code == 400
        assert error_code(response) == "validation_error"

    def test_ended_period_returns_400(self, client_for, employee):
        now = timezone.now()
        ended = Period.objects.create(name="Old", start_at=now - timedelta(days=30), end_at=now - timedelta(days=1))

        response = submit(client_for(employee), ended.id)

        assert response.status_code == 400
        assert "period_id" in response.json()["error"]["details"]

    def test_period_end_is_exclusive(self, client_for, employee, period, frozen_clock):
        # The bounds are [start_at, end_at), so at exactly end_at the period is over.
        frozen_clock.current = period.end_at - timedelta(microseconds=1)
        assert submit(client_for(employee), period.id).status_code == 201

        frozen_clock.current = period.end_at
        assert submit(client_for(employee), period.id).status_code == 400

    @pytest.mark.parametrize("user_fixture", ["manager", "hr"])
    def test_only_employees_can_submit(self, request, client_for, period, user_fixture):
        # Product assumption: managers and HR are not applicants in this version.
        user = request.getfixturevalue(user_fixture)

        response = submit(client_for(user), period.id)

        assert response.status_code == 403
        assert error_code(response) == "forbidden"

    def test_not_logged_in_returns_401(self, api_client, period):
        response = submit(api_client, period.id)

        assert response.status_code == 401
        assert error_code(response) == "not_authenticated"


@pytest.mark.django_db
class TestVisibility:
    @pytest.fixture
    def requests(self, make_request, make_user, employee, other_employee, other_team):
        outsider = make_user("olga", team=other_team)
        return {
            "alice": make_request(employee),
            "bob": make_request(other_employee),
            "olga": make_request(outsider),
        }

    def ids(self, response):
        return {item["id"] for item in response.json()["results"]}

    def test_employee_sees_only_own_requests(self, client_for, employee, requests):
        response = client_for(employee).get(REQUESTS_URL)

        assert self.ids(response) == {requests["alice"].id}

    def test_manager_sees_own_team_only(self, client_for, manager, requests):
        response = client_for(manager).get(REQUESTS_URL)

        assert self.ids(response) == {requests["alice"].id, requests["bob"].id}

    def test_hr_sees_every_team(self, client_for, hr, requests):
        response = client_for(hr).get(REQUESTS_URL)

        assert self.ids(response) == {r.id for r in requests.values()}

    def test_owner_can_read_detail_with_reason(self, client_for, employee, requests):
        response = client_for(employee).get(detail_url(requests["alice"].id))

        assert response.status_code == 200
        assert response.json()["reason"] == "Doctor visit"

    @pytest.mark.parametrize(
        "viewer, target",
        [
            ("employee", "bob"),  # a teammate's request
            ("manager", "olga"),  # a request from another team
        ],
    )
    def test_no_access_returns_404_like_a_missing_record(self, request, client_for, requests, viewer, target):
        client = client_for(request.getfixturevalue(viewer))

        hidden = client.get(detail_url(requests[target].id))
        missing = client.get(detail_url(999999))

        assert hidden.status_code == missing.status_code == 404
        # Same body, so the caller cannot tell "hidden" apart from "does not exist".
        assert hidden.json() == missing.json()
        assert error_code(hidden) == "not_found"


@pytest.mark.django_db
class TestListFiltersAndPagination:
    def test_filter_by_status(self, client_for, make_request, employee, hr):
        pending = make_request(employee)
        rejected = make_request(employee)
        rejected.status, rejected.decided_at = "rejected", timezone.now()
        rejected.save()

        response = client_for(hr).get(REQUESTS_URL, {"status": "rejected"})

        assert [r["id"] for r in response.json()["results"]] == [rejected.id]
        assert pending.id not in [r["id"] for r in response.json()["results"]]

    def test_filter_by_period(self, client_for, make_request, employee, hr, period):
        other = Period.objects.create(
            name="Next", start_at=period.end_at, end_at=period.end_at + timedelta(days=30)
        )
        make_request(employee)
        in_other = make_request(employee, for_period=other)

        response = client_for(hr).get(REQUESTS_URL, {"period_id": other.id})

        assert [r["id"] for r in response.json()["results"]] == [in_other.id]

    def test_bad_filter_returns_400(self, client_for, hr):
        response = client_for(hr).get(REQUESTS_URL, {"status": "maybe"})

        assert response.status_code == 400
        assert error_code(response) == "validation_error"

    def test_newest_first_with_id_as_tie_breaker(self, client_for, make_request, employee):
        created = [make_request(employee) for _ in range(3)]
        # Give every row the same created_at, so only the id can order them.
        same_time = timezone.now()
        QuotaRequest.objects.filter(pk__in=[r.pk for r in created]).update(created_at=same_time)

        response = client_for(employee).get(REQUESTS_URL)

        assert [r["id"] for r in response.json()["results"]] == sorted((r.id for r in created), reverse=True)

    def test_default_page_size_is_20(self, client_for, make_request, employee):
        for _ in range(25):
            make_request(employee)

        body = client_for(employee).get(REQUESTS_URL).json()

        assert body["count"] == 25
        assert len(body["results"]) == 20
        assert body["next"] is not None

    def test_page_size_is_capped_at_100(self, client_for, make_request, employee):
        for _ in range(105):
            make_request(employee)

        body = client_for(employee).get(REQUESTS_URL, {"page_size": 500}).json()

        assert len(body["results"]) == 100

    def test_pages_do_not_overlap(self, client_for, make_request, employee):
        for _ in range(5):
            make_request(employee)
        client = client_for(employee)

        first = client.get(REQUESTS_URL, {"page_size": 3}).json()["results"]
        second = client.get(REQUESTS_URL, {"page_size": 3, "page": 2}).json()["results"]

        ids = [r["id"] for r in first + second]
        assert len(ids) == len(set(ids)) == 5

    def test_page_out_of_range_returns_404(self, client_for, employee):
        response = client_for(employee).get(REQUESTS_URL, {"page": 99})

        assert response.status_code == 404
        assert error_code(response) == "not_found"


@pytest.mark.django_db
class TestPeriods:
    def test_lists_periods_with_open_flag(self, client_for, employee, period):
        ended = Period.objects.create(
            name="Old",
            start_at=period.start_at - timedelta(days=60),
            end_at=period.start_at - timedelta(days=30),
        )

        response = client_for(employee).get("/api/v1/periods/")

        assert response.status_code == 200
        flags = {p["id"]: p["is_open"] for p in response.json()}
        assert flags == {period.id: True, ended.id: False}

    def test_needs_login(self, api_client):
        assert api_client.get("/api/v1/periods/").status_code == 401
