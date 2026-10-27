"""Rate limit tests. Time is moved with frozen_clock, so nothing here sleeps."""

import pytest
import redis

from utils import ratelimit
from utils.testing.api import REQUESTS_URL, error_code, submit

LOGIN_URL = "/api/v1/auth/token/"


@pytest.fixture
def small_limits(settings):
    settings.RATE_LIMIT_WRITE_PER_MINUTE = 3
    settings.RATE_LIMIT_READ_PER_MINUTE = 5


@pytest.mark.django_db
@pytest.mark.usefixtures("small_limits")
class TestRateLimit:
    def test_write_limit_returns_429_with_retry_after(self, client_for, employee, period, frozen_clock):
        client = client_for(employee)
        for _ in range(3):
            assert submit(client, period.id).status_code == 201

        response = submit(client, period.id)

        assert response.status_code == 429
        assert error_code(response) == "rate_limited"
        # The clock is at second 30, so the window opens again in 30 seconds.
        assert response.headers["Retry-After"] == "30"

    def test_window_opens_again_next_minute(self, client_for, employee, period, frozen_clock):
        client = client_for(employee)
        for _ in range(3):
            submit(client, period.id)
        assert submit(client, period.id).status_code == 429

        frozen_clock.advance(seconds=29)
        assert submit(client, period.id).status_code == 429

        frozen_clock.advance(seconds=1)
        assert submit(client, period.id).status_code == 201

    def test_read_limit(self, client_for, employee, frozen_clock):
        client = client_for(employee)
        for _ in range(5):
            assert client.get(REQUESTS_URL).status_code == 200

        response = client.get(REQUESTS_URL)

        assert response.status_code == 429
        assert error_code(response) == "rate_limited"

    def test_reads_and_writes_have_separate_counters(self, client_for, employee, period, frozen_clock):
        client = client_for(employee)
        for _ in range(3):
            submit(client, period.id)

        assert client.get(REQUESTS_URL).status_code == 200

    def test_each_user_has_own_counter(self, client_for, employee, other_employee, period, frozen_clock):
        for _ in range(3):
            submit(client_for(employee), period.id)

        assert submit(client_for(employee), period.id).status_code == 429
        assert submit(client_for(other_employee), period.id).status_code == 201

    def test_replays_are_counted(self, client_for, employee, period, frozen_clock):
        client = client_for(employee)
        submit(client, period.id, key="same")
        submit(client, period.id, key="same")
        submit(client, period.id, key="same")

        response = submit(client, period.id, key="same")

        assert response.status_code == 429

    def test_rejected_requests_are_counted_too(self, client_for, employee, period, frozen_clock):
        client = client_for(employee)
        for _ in range(3):
            assert submit(client, period.id, minutes=0).status_code == 400

        assert submit(client, period.id).status_code == 429

    def test_limits_come_from_settings(self, client_for, employee, period, frozen_clock, settings):
        settings.RATE_LIMIT_WRITE_PER_MINUTE = 1
        client = client_for(employee)

        assert submit(client, period.id).status_code == 201
        assert submit(client, period.id).status_code == 429

    def test_fails_open_when_redis_is_down(self, client_for, employee, period, frozen_clock, monkeypatch):
        # Nothing listens on port 1, so every Redis call fails.
        dead = redis.Redis.from_url("redis://localhost:1/0", socket_connect_timeout=0.1)
        monkeypatch.setattr(ratelimit, "redis_client", dead)
        client = client_for(employee)

        for _ in range(5):
            assert submit(client, period.id).status_code == 201

    def test_anonymous_requests_get_401_not_429(self, api_client, frozen_clock):
        # Protected endpoints reject anonymous users before the rate limit runs.
        for _ in range(10):
            assert api_client.get(REQUESTS_URL).status_code == 401

    def test_login_is_limited_per_ip(self, api_client, employee, frozen_clock):
        wrong = {"username": employee.username, "password": "wrong"}
        for _ in range(3):
            assert api_client.post(LOGIN_URL, wrong, format="json").status_code == 401

        response = api_client.post(LOGIN_URL, wrong, format="json")

        assert response.status_code == 429
        assert error_code(response) == "rate_limited"

    def test_fake_forwarded_for_does_not_reset_the_limit(self, api_client, employee, frozen_clock):
        wrong = {"username": employee.username, "password": "wrong"}
        for i in range(3):
            api_client.post(LOGIN_URL, wrong, format="json", headers={"X-Forwarded-For": f"10.0.0.{i}"})

        response = api_client.post(LOGIN_URL, wrong, format="json", headers={"X-Forwarded-For": "10.0.0.99"})

        assert response.status_code == 429

    def test_other_ip_has_own_login_limit(self, client, employee, frozen_clock):
        wrong = {"username": employee.username, "password": "wrong"}
        for _ in range(3):
            client.post(LOGIN_URL, wrong, content_type="application/json", REMOTE_ADDR="1.1.1.1")

        response = client.post(LOGIN_URL, wrong, content_type="application/json", REMOTE_ADDR="2.2.2.2")

        assert response.status_code == 401

