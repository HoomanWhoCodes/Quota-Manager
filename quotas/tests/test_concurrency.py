"""Real concurrency tests on PostgreSQL.

How the overlap is made (no sleep-and-hope):
1. A "holder" thread opens a transaction and locks the row both workers need.
2. Two worker threads send their HTTP requests. Each runs in its own thread,
   so Django gives it its own database connection.
3. We poll pg_stat_activity until PostgreSQL says both workers are waiting
   on a lock. Now we know for sure that both transactions are open at once.
4. We release the holder. PostgreSQL hands the lock to the workers one by one.
5. We check the HTTP responses and the database.

Lock waiters are queued in order, so starting worker 2 only after worker 1 is
waiting also fixes who goes first. That lets us test both orders on purpose.
"""

import threading
import time
from contextlib import contextmanager

import pytest
from django.db import connection, connections, transaction

from quotas.models import Decision, EventType, Quota, QuotaRequest, RequestEvent
from utils.models import IdempotencyKey
from utils.testing.api import decide, error_code

TIMEOUT = 10

pytestmark = pytest.mark.django_db(transaction=True)


def lock_waiters():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() AND wait_event_type = 'Lock'"
        )
        return cursor.fetchone()[0]


def wait_for_lock_waiters(count):
    deadline = time.monotonic() + TIMEOUT
    while lock_waiters() < count:
        if time.monotonic() > deadline:
            raise AssertionError(f"Expected {count} transactions waiting on a lock")
        time.sleep(0.01)


def in_thread(fn):
    """Run fn in a new thread (so with its own DB connection). Returns a result getter."""
    result = {}

    def target():
        try:
            result["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised in the test thread
            result["error"] = exc
        finally:
            connections.close_all()

    thread = threading.Thread(target=target)
    thread.start()

    def get():
        thread.join(TIMEOUT)
        assert not thread.is_alive(), "worker thread is stuck"
        if "error" in result:
            raise result["error"]
        return result["value"]

    return get


@contextmanager
def holding(lock_fn):
    """Run lock_fn in an open transaction on another connection, and keep it open."""
    locked, release = threading.Event(), threading.Event()

    def hold():
        with transaction.atomic():
            lock_fn()
            locked.set()
            release.wait(TIMEOUT)

    done = in_thread(hold)
    assert locked.wait(TIMEOUT)
    try:
        yield release.set
    finally:
        release.set()
        done()


def lock_row(model, pk):
    return lambda: model.objects.select_for_update().get(pk=pk)


def final_events(request):
    return RequestEvent.objects.filter(
        request=request, event_type__in=[EventType.APPROVED, EventType.REJECTED]
    ).count()


@pytest.fixture
def two_hr(make_user):
    return make_user("hana", role="hr"), make_user("henry", role="hr")


class TestTwoFinalApprovalsCompeteForQuota:
    """Mandatory scenario 1: two 300-minute requests, both already approved once."""

    @pytest.mark.parametrize("quota_row_exists", [True, False])
    def test_only_one_is_approved(self, client_for, make_request, employee, manager, two_hr, period, quota_row_exists):
        r1 = make_request(employee, minutes=300)
        r2 = make_request(employee, minutes=300)
        for r in (r1, r2):
            decide(client_for(manager), r.id, "approve")
        hr_a, hr_b = (client_for(u) for u in two_hr)

        if quota_row_exists:
            quota = Quota.objects.create(employee=employee, period=period)
            hold = lock_row(Quota, quota.pk)
        else:
            # Nobody has a quota row yet. The holder inserts it and does not
            # commit, so both workers block on their own insert of the same row.
            def hold():
                Quota.objects.create(employee=employee, period=period)

        with holding(hold) as release:
            first = in_thread(lambda: decide(hr_a, r1.id, "approve"))
            second = in_thread(lambda: decide(hr_b, r2.id, "approve"))
            wait_for_lock_waiters(2)
            release()
            responses = [first(), second()]

        statuses = sorted(r.status_code for r in responses)
        assert statuses == [200, 409]
        loser = next(r for r in responses if r.status_code == 409)
        assert error_code(loser) == "quota_exceeded"

        assert Quota.objects.filter(employee=employee, period=period).count() == 1
        assert Quota.objects.get(employee=employee, period=period).consumed_minutes == 300
        assert QuotaRequest.objects.filter(status="approved").count() == 1
        assert QuotaRequest.objects.filter(status="pending").count() == 1
        loser_request = QuotaRequest.objects.get(status="pending")
        # The loser keeps only its first (manager) approval.
        assert list(loser_request.decisions.values_list("role", flat=True)) == ["manager"]
        assert final_events(loser_request) == 0


class TestDuplicateFinalApproval:
    """Mandatory scenario 2: the same final approval sent twice at the same time."""

    def test_quota_is_used_once_and_one_final_event(self, client_for, make_request, employee, manager, hr, period):
        request = make_request(employee, minutes=200)
        decide(client_for(manager), request.id, "approve")
        # Two different keys, like a double click on a client that makes a key per click.
        a, b = client_for(hr), client_for(hr)

        with holding(lock_row(QuotaRequest, request.pk)) as release:
            first = in_thread(lambda: decide(a, request.id, "approve", key="click-1"))
            second = in_thread(lambda: decide(b, request.id, "approve", key="click-2"))
            wait_for_lock_waiters(2)
            release()
            responses = [first(), second()]

        assert sorted(r.status_code for r in responses) == [200, 409]
        loser = next(r for r in responses if r.status_code == 409)
        assert error_code(loser) == "invalid_state"

        request.refresh_from_db()
        assert request.status == "approved"
        assert Quota.objects.get(employee=employee, period=period).consumed_minutes == 200
        assert request.decisions.filter(role="hr").count() == 1
        assert final_events(request) == 1


class TestSameIdempotencyKeyAtOnce:
    """Two requests with one key: the second waits for the first, then replays it."""

    def test_second_waits_then_replays(self, client_for, make_request, employee, manager, hr, period):
        request = make_request(employee, minutes=100)
        decide(client_for(manager), request.id, "approve")
        a, b = client_for(hr), client_for(hr)

        with holding(lock_row(QuotaRequest, request.pk)) as release:
            # Worker 1 saves the key, then waits for the request row.
            first = in_thread(lambda: decide(a, request.id, "approve", key="same"))
            wait_for_lock_waiters(1)
            # Worker 2 now waits on the key's unique index, behind worker 1.
            second = in_thread(lambda: decide(b, request.id, "approve", key="same"))
            wait_for_lock_waiters(2)
            release()
            r1, r2 = first(), second()

        assert r1.status_code == r2.status_code == 200
        assert r2.json() == r1.json()
        assert r2.headers["Idempotent-Replayed"] == "true"
        assert "Idempotent-Replayed" not in r1.headers
        assert request.decisions.filter(role="hr").count() == 1
        assert IdempotencyKey.objects.filter(user=hr, key="same").count() == 1
        assert Quota.objects.get(employee=employee, period=period).consumed_minutes == 100


class TestApproveAndRejectAtOnce:
    """Whoever gets the request row lock first wins. Both orders end REJECTED."""

    def run(self, client_for, request, first, second):
        with holding(lock_row(QuotaRequest, request.pk)) as release:
            r1 = in_thread(lambda: decide(client_for(first[0]), request.id, first[1]))
            wait_for_lock_waiters(1)
            r2 = in_thread(lambda: decide(client_for(second[0]), request.id, second[1]))
            wait_for_lock_waiters(2)
            release()
            return r1(), r2()

    def test_approve_first_then_reject(self, client_for, make_request, employee, manager, hr, period):
        request = make_request(employee)

        approve, reject = self.run(client_for, request, (manager, "approve"), (hr, "reject"))

        assert approve.status_code == 200
        assert approve.json()["request"]["status"] == "pending"
        assert reject.status_code == 200
        assert reject.json()["request"]["status"] == "rejected"
        request.refresh_from_db()
        assert request.status == "rejected"
        assert Decision.objects.filter(request=request).count() == 2
        assert final_events(request) == 1
        assert not Quota.objects.filter(consumed_minutes__gt=0).exists()

    def test_reject_first_then_approve(self, client_for, make_request, employee, manager, hr, period):
        request = make_request(employee)

        reject, approve = self.run(client_for, request, (hr, "reject"), (manager, "approve"))

        assert reject.status_code == 200
        assert approve.status_code == 409
        assert error_code(approve) == "invalid_state"
        request.refresh_from_db()
        assert request.status == "rejected"
        assert Decision.objects.filter(request=request).count() == 1
        assert final_events(request) == 1
        assert not Quota.objects.filter(consumed_minutes__gt=0).exists()
