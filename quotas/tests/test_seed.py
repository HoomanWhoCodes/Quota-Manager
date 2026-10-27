from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from accounts.models import User
from quotas.models import Period
from utils import clock


def run_seed(**options):
    call_command("seed", stdout=StringIO(), **options)


@pytest.mark.django_db
class TestSeed:
    def test_creates_users_for_every_role(self):
        run_seed(force=True)

        engineering = User.objects.filter(team__name="Engineering")
        assert engineering.filter(role="employee").count() == 2
        assert engineering.filter(role="manager").count() == 1
        assert User.objects.filter(role="hr", is_superuser=False).count() == 1

    def test_creates_admin_superuser(self):
        run_seed(force=True)

        admin = User.objects.get(username="admin")
        assert admin.is_superuser and admin.is_staff

    def test_period_is_open_now(self):
        run_seed(force=True)

        now = clock.now()
        assert Period.objects.filter(start_at__lte=now, end_at__gt=now).exists()

    def test_running_twice_is_safe(self):
        run_seed(force=True)
        run_seed(force=True)

        assert Period.objects.count() == 1
        assert User.objects.filter(username="alice").count() == 1

    def test_fake_token_works(self, client):
        run_seed(force=True)

        response = client.get("/api/v1/requests/", headers={"Authorization": "Token alice-fake-token"})

        assert response.status_code == 200

    def test_refuses_to_run_with_debug_off(self, settings):
        settings.DEBUG = False

        with pytest.raises(CommandError):
            run_seed()

    def test_reset_deletes_requests_and_quotas(self, client):
        from quotas.models import Quota, QuotaRequest, RequestEvent
        from quotas.services import decide, submit_request

        run_seed(force=True)
        alice, maria, hana = (User.objects.get(username=n) for n in ("alice", "maria", "hana"))
        request = submit_request(employee=alice, period_id=Period.objects.get().id, minutes=60, reason="x")
        decide(actor=maria, request_id=request.id, outcome="approve")
        decide(actor=hana, request_id=request.id, outcome="approve")

        run_seed(force=True, reset=True)

        assert not QuotaRequest.objects.exists()
        assert not Quota.objects.exists()
        assert not RequestEvent.objects.exists()
        assert User.objects.filter(username="alice").exists()
        assert Period.objects.count() == 1
