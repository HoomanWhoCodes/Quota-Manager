from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import Team, User
from quotas.models import Period
from quotas.services import submit_request
from utils import clock

PASSWORD = "test-password"


@pytest.fixture(autouse=True)
def clear_rate_limits():
    # Rate limit counters live in Redis, not in the test database, so start
    # every test with an empty cache.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def team(db):
    return Team.objects.create(name="Engineering")


@pytest.fixture
def other_team(db):
    return Team.objects.create(name="Sales")


@pytest.fixture
def make_user(db):
    def make(username, role=User.Role.EMPLOYEE, team=None):
        return User.objects.create_user(username=username, password=PASSWORD, role=role, team=team)

    return make


@pytest.fixture
def employee(make_user, team):
    return make_user("alice", team=team)


@pytest.fixture
def other_employee(make_user, team):
    return make_user("bob", team=team)


@pytest.fixture
def manager(make_user, team):
    return make_user("maria", role=User.Role.MANAGER, team=team)


@pytest.fixture
def other_manager(make_user, other_team):
    return make_user("sam", role=User.Role.MANAGER, team=other_team)


@pytest.fixture
def hr(make_user):
    return make_user("hana", role=User.Role.HR)


@pytest.fixture
def period(db):
    now = timezone.now()
    return Period.objects.create(name="Open", start_at=now - timedelta(days=1), end_at=now + timedelta(days=30))


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def client_for():
    """An API client logged in as the given user, using token auth."""

    def make(user):
        client = APIClient()
        token, _ = Token.objects.get_or_create(user=user)
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return client

    return make


class FrozenClock:
    """A clock that only moves when the test calls advance()."""

    def __init__(self):
        self.current = timezone.now().replace(second=30, microsecond=0)

    def now(self):
        return self.current

    def advance(self, **delta):
        self.current += timedelta(**delta)


@pytest.fixture
def frozen_clock(monkeypatch):
    """Stops the app clock at second 30 of the current minute."""
    frozen = FrozenClock()
    monkeypatch.setattr(clock, "now", frozen.now)
    return frozen


@pytest.fixture
def make_request(period):
    """Creates a request through the domain service, not through HTTP."""

    def make(employee, minutes=60, reason="Doctor visit", for_period=None):
        return submit_request(
            employee=employee,
            period_id=(for_period or period).id,
            minutes=minutes,
            reason=reason,
        )

    return make
