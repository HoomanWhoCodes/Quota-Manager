
import pytest
from django.core.management import call_command

from quotas.models import Decision, QuotaRequest, RequestEvent
from utils.models import IdempotencyKey
from utils.testing.api import REQUESTS_URL, decide, error_code, submit


@pytest.mark.django_db
class TestMissingKey:
    def test_submit_without_key_returns_400(self, client_for, employee, period):
        response = client_for(employee).post(
            REQUESTS_URL, {"period_id": period.id, "minutes": 60, "reason": "x"}, format="json"
        )

        assert response.status_code == 400
        assert error_code(response) == "idempotency_key_missing"
        assert not QuotaRequest.objects.exists()

    def test_decide_without_key_returns_400(self, client_for, make_request, employee, manager):
        request = make_request(employee)

        response = client_for(manager).post(
            f"{REQUESTS_URL}{request.id}/decisions/", {"decision": "approve"}, format="json"
        )

        assert response.status_code == 400
        assert error_code(response) == "idempotency_key_missing"
        assert not Decision.objects.exists()

    def test_too_long_key_returns_400(self, client_for, employee, period):
        response = submit(client_for(employee), period.id, key="k" * 256)

        assert response.status_code == 400
        assert error_code(response) == "validation_error"


@pytest.mark.django_db
class TestReplay:
    def test_same_key_and_body_replays_submit(self, client_for, employee, period):
        client = client_for(employee)

        first = submit(client, period.id, minutes=90, key="abc")
        second = submit(client, period.id, minutes=90, key="abc")

        assert first.status_code == second.status_code == 201
        assert second.json() == first.json()
        assert second.headers["Idempotent-Replayed"] == "true"
        assert "Idempotent-Replayed" not in first.headers
        assert QuotaRequest.objects.count() == 1
        assert RequestEvent.objects.count() == 1

    def test_same_key_and_body_replays_decision(self, client_for, make_request, employee, manager, hr, period):
        request = make_request(employee, minutes=100)
        decide(client_for(manager), request.id, "approve")
        hr_client = client_for(hr)

        first = decide(hr_client, request.id, "approve", key="hr-1")
        second = decide(hr_client, request.id, "approve", key="hr-1")

        assert first.status_code == second.status_code == 200
        assert second.json() == first.json()
        assert Decision.objects.filter(request=request).count() == 2
        assert request.events.filter(event_type="approved").count() == 1
        assert employee.quotas.get(period=period).consumed_minutes == 100

    def test_json_key_order_does_not_matter(self, client_for, employee, period):
        client = client_for(employee)
        headers = {"Idempotency-Key": "abc"}

        client.post(REQUESTS_URL, {"period_id": period.id, "minutes": 5, "reason": "x"}, format="json", headers=headers)
        second = client.post(
            REQUESTS_URL, {"reason": "x", "minutes": 5, "period_id": period.id}, format="json", headers=headers
        )

        assert second.status_code == 201
        assert second.headers["Idempotent-Replayed"] == "true"

    def test_a_new_key_creates_a_new_request(self, client_for, employee, period):
        client = client_for(employee)

        submit(client, period.id, key="one")
        submit(client, period.id, key="two")

        assert QuotaRequest.objects.count() == 2


@pytest.mark.django_db
class TestKeyReuse:
    def test_same_key_different_body_returns_409(self, client_for, employee, period):
        client = client_for(employee)
        submit(client, period.id, minutes=60, key="abc")

        response = submit(client, period.id, minutes=61, key="abc")

        assert response.status_code == 409
        assert error_code(response) == "idempotency_key_reuse"
        assert QuotaRequest.objects.count() == 1

    def test_same_key_on_another_request_returns_409(self, client_for, make_request, employee, hr):
        # The path is part of the fingerprint, so a key can't jump to a different target.
        first, second = make_request(employee), make_request(employee)
        client = client_for(hr)
        decide(client, first.id, "reject", key="abc")

        response = decide(client, second.id, "reject", key="abc")

        assert error_code(response) == "idempotency_key_reuse"
        second.refresh_from_db()
        assert second.status == "pending"

    def test_same_key_on_another_operation_returns_409(self, client_for, employee, period):
        client = client_for(employee)
        request_id = submit(client, period.id, key="abc").json()["id"]

        response = decide(client, request_id, "approve", key="abc")

        assert error_code(response) == "idempotency_key_reuse"

    def test_keys_are_scoped_per_user(self, client_for, employee, other_employee, period):
        a = submit(client_for(employee), period.id, key="same")
        b = submit(client_for(other_employee), period.id, key="same")

        assert a.status_code == b.status_code == 201
        assert a.json()["id"] != b.json()["id"]


@pytest.mark.django_db
class TestWhatIsStored:
    def test_validation_error_is_not_stored(self, client_for, employee, period):
        # The client can fix the body and try again with the same key.
        client = client_for(employee)

        bad = submit(client, period.id, minutes=0, key="abc")
        good = submit(client, period.id, minutes=30, key="abc")

        assert bad.status_code == 400
        assert good.status_code == 201
        assert "Idempotent-Replayed" not in good.headers

    def test_conflict_is_stored_and_replayed(self, client_for, make_request, employee, manager, hr):
        request = make_request(employee)
        decide(client_for(hr), request.id, "reject")
        client = client_for(manager)

        first = decide(client, request.id, "approve", key="m-1")
        second = decide(client, request.id, "approve", key="m-1")

        assert first.status_code == second.status_code == 409
        assert second.json() == first.json()
        assert second.headers["Idempotent-Replayed"] == "true"

    def test_not_found_is_stored(self, client_for, make_request, employee, other_manager):
        request = make_request(employee)
        client = client_for(other_manager)

        decide(client, request.id, "approve", key="x")
        second = decide(client, request.id, "approve", key="x")

        assert second.status_code == 404
        assert second.headers["Idempotent-Replayed"] == "true"

    def test_quota_exceeded_is_stored(self, client_for, make_request, employee, manager, hr):
        big = make_request(employee, minutes=480)
        decide(client_for(manager), big.id, "approve")
        decide(client_for(hr), big.id, "approve")
        small = make_request(employee, minutes=1)
        decide(client_for(manager), small.id, "approve")

        first = decide(client_for(hr), small.id, "approve", key="h")
        second = decide(client_for(hr), small.id, "approve", key="h")

        assert error_code(first) == error_code(second) == "quota_exceeded"
        assert second.headers["Idempotent-Replayed"] == "true"


@pytest.mark.django_db
class TestRetention:
    def test_key_can_be_reused_after_it_expires(self, client_for, employee, period, frozen_clock, settings):
        client = client_for(employee)
        submit(client, period.id, minutes=10, key="abc")

        frozen_clock.advance(hours=settings.IDEMPOTENCY_KEY_TTL_HOURS, seconds=1)
        response = submit(client, period.id, minutes=20, key="abc")

        assert response.status_code == 201
        assert "Idempotent-Replayed" not in response.headers
        assert QuotaRequest.objects.count() == 2

    def test_key_still_works_just_before_expiry(self, client_for, employee, period, frozen_clock, settings):
        client = client_for(employee)
        submit(client, period.id, minutes=10, key="abc")

        frozen_clock.advance(hours=settings.IDEMPOTENCY_KEY_TTL_HOURS, seconds=-1)
        response = submit(client, period.id, minutes=10, key="abc")

        assert response.headers["Idempotent-Replayed"] == "true"

    def test_purge_command_deletes_only_old_keys(self, client_for, employee, period, frozen_clock, settings):
        client = client_for(employee)
        submit(client, period.id, key="old")
        frozen_clock.advance(hours=settings.IDEMPOTENCY_KEY_TTL_HOURS + 1)
        submit(client, period.id, key="new")

        call_command("purge_expired")

        assert list(IdempotencyKey.objects.values_list("key", flat=True)) == ["new"]
