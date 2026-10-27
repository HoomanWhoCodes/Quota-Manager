# Quota Manager

A backend service for employee request quotas. Each employee gets 480 minutes per period.
A request needs approval from both the team manager and HR. Minutes are taken from the
quota only when the second approval succeeds.

Built with Django + Django REST Framework, PostgreSQL and Redis.

- [Versions](#versions)
- [Setup](#setup)
- [Authentication](#authentication)
- [API](#api)
- [Error contract](#error-contract)
- [Invariants and where they are enforced](#invariants-and-where-they-are-enforced)
- [Required decisions](#required-decisions)
- [Tests](#tests)
- [Assumptions](#assumptions)
- [Limitations and what I would do next](#limitations-and-what-i-would-do-next)

## Versions

| Tool | Version |
|---|---|
| Python | 3.13.7 |
| uv | 0.12.17 |
| Django | 5.2.18 |
| Django REST Framework | 3.18.3 |
| djangorestframework-simplejwt | 5.5.1 |
| django-environ | 0.14.0 |
| psycopg | 3.3.6 |
| redis (Python client) | 8.1.0 |
| pytest | 9.1.1 |
| pytest-django | 4.14.0 |
| PostgreSQL | 17 (`postgres:17` image, tested on 17.10) |
| Redis | 8 (`redis:8` image, tested on 8.10.2) |

## Setup

You need Docker (for PostgreSQL and Redis) and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env              # all values in it are fake and local-only
docker compose up -d              # PostgreSQL on port 5433, Redis on port 6380
uv sync                           # install Python and dependencies
uv run python manage.py migrate
uv run python manage.py seed      # sample period, users and tokens (--reset clears old requests)
uv run python manage.py runserver
```

The ports are 5433 and 6380 so they don't clash with a PostgreSQL or Redis you may already
run locally. You can change them in `.env`.

If you'd rather use a local PostgreSQL, point `DATABASE_URL` in `.env` at it. Redis is still
needed for the rate limiter.

### Sample data

`seed` creates a period that starts today and lasts 30 days, so it is always open when you
run the project. Running it again is safe: it reuses the open period. If that period has
ended, it makes a new one.

All passwords and tokens are **fake** and only for local testing.

| User | Role | Team | Password | Token |
|---|---|---|---|---|
| alice | employee | Engineering | password123 | alice-fake-token |
| bob | employee | Engineering | password123 | bob-fake-token |
| maria | manager | Engineering | password123 | maria-fake-token |
| sam | manager | Sales | password123 | sam-fake-token |
| hana | HR | - | password123 | hana-fake-token |
| admin | HR, superuser | - | password123 | admin-fake-token |

`sam` is there so you can see the 404 for a manager of another team. `admin` is for the
Django admin at `/admin/`. It has the HR role because every user needs a role, and HR is
the one that doesn't need a team.

The command refuses to run when `DEBUG` is off, because the passwords are fake. Use
`--force` if you really want that.

### Cleanup job

Idempotency keys older than `IDEMPOTENCY_KEY_TTL_HOURS` can be deleted with:

```bash
uv run python manage.py purge_expired
```

In production this would run from cron. The service is still correct if it never runs,
because an expired key is also deleted when someone tries to reuse it.

## Authentication

Two ways to log in. Both are local users, and there is no SSO.

1. **JWT.** `POST /api/v1/auth/token/` with `{"username": "...", "password": "..."}` returns
   `access` and `refresh`. Send `Authorization: Bearer <access>`. Access tokens live 15
   minutes and refresh tokens live 1 day (`JWT_ACCESS_MINUTES`, `JWT_REFRESH_DAYS`). Get a
   new access token with `POST /api/v1/auth/token/refresh/` and `{"refresh": "..."}`.
2. **Static token**, for quick testing: `Authorization: Token <token>`. The seed command
   prints a token for every user.

Every endpoint except login needs authentication. Without it you get `401
not_authenticated`.

## API

All routes are under `/api/v1/`. Request and response bodies are JSON. Every route ends
with `/`. Without it you get `404` (there is no redirect, because a redirect would lose the
body of a POST).

| Method | Route | Notes |
|---|---|---|
| POST | `/requests/` | `period_id`, `minutes` (1–480), `reason`. Needs `Idempotency-Key`. Employees only. Returns `201` with the request in `pending`. |
| GET | `/requests/` | Filters: `status`, `period_id`. Pagination: `page`, `page_size`. Employees see their own requests, managers see their team's, HR sees all. |
| GET | `/requests/{id}/` | The request with its decisions. `404` if you can't see it. |
| POST | `/requests/{id}/decisions/` | `{"decision": "approve" \| "reject"}`. Needs `Idempotency-Key`. Returns your decision and the new request status. |
| GET | `/quotas/{period_id}/` | Ceiling, consumed and remaining minutes for **the logged-in user**. There is no way to ask for someone else's quota. |
| GET | `/periods/` | **Extra, not in the task.** Read-only list of periods with an `is_open` flag, so a client can find the open period. |

### Sample requests

Submit a request as alice:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/requests/ \
  -H "Authorization: Token alice-fake-token" \
  -H "Idempotency-Key: 6f1c2a9e-3b7d-4e0f-9a51-2c8d4b6e1f70" \
  -H "Content-Type: application/json" \
  -d '{"period_id": 1, "minutes": 120, "reason": "Dentist appointment"}'
```

```http
HTTP/1.1 201 Created

{
  "id": 15,
  "employee_id": 23,
  "period_id": 1,
  "minutes": 120,
  "reason": "Dentist appointment",
  "status": "pending",
  "decisions": [],
  "created_at": "2026-10-26T14:21:59.033326Z",
  "decided_at": null
}
```

Sending the same call again with the same key returns the same body and status, plus the
header `Idempotent-Replayed: true`. Nothing new is created.

maria (manager) approves, then hana (HR) approves:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/requests/15/decisions/ \
  -H "Authorization: Token hana-fake-token" \
  -H "Idempotency-Key: 0b5e7c43-8d21-4f6a-b9e2-7a3c1d5f8e94" \
  -H "Content-Type: application/json" \
  -d '{"decision": "approve"}'
```

```json
{
  "decision": {"role": "hr", "outcome": "approve", "actor_id": 27, "created_at": "2026-10-26T14:21:59.202934Z"},
  "request": {"id": 15, "status": "approved"}
}
```

Check the quota:

```bash
curl http://127.0.0.1:8000/api/v1/quotas/1/ -H "Authorization: Token alice-fake-token"
```

```json
{"period_id": 1, "ceiling_minutes": 480, "consumed_minutes": 120, "remaining_minutes": 360}
```

A manager of another team trying to read it:

```http
HTTP/1.1 404 Not Found

{"error": {"code": "not_found", "message": "Not found.", "details": null}}
```

## Error contract

Every error has the same shape:

```json
{"error": {"code": "machine_readable_code", "message": "Text for humans.", "details": null}}
```

`details` is only filled for validation errors, with the problem for each field.

Errors that happen outside the API views (a wrong URL, a crash) use the same shape too.
With `DEBUG` on, Django shows its own debug page for those instead, which is what you
want while developing.

| HTTP | Code | When |
|---|---|---|
| 400 | `validation_error` | Bad input, unknown or ended period, bad filter, too long `Idempotency-Key` |
| 400 | `idempotency_key_missing` | `Idempotency-Key` header is missing on a POST that needs it |
| 401 | `not_authenticated` | No credentials, or a bad or expired token |
| 403 | `forbidden` | Reviewing your own request, or a manager or HR trying to submit |
| 404 | `not_found` | The record doesn't exist **or** you can't see it (same body in both cases). Also a wrong URL. |
| 405 | `method_not_allowed` | Wrong HTTP method |
| 409 | `invalid_state` | Your role already decided, or the request is already finished |
| 409 | `idempotency_key_reuse` | Same key sent with a different body or to a different route |
| 409 | `quota_exceeded` | Second approval, but not enough minutes left |
| 415 | `unsupported_media_type` | Body is not JSON |
| 429 | `rate_limited` | Too many requests. Comes with a `Retry-After` header |
| 500 | `server_error` | A bug. Nothing is stored for idempotency, so a retry is safe |

## Invariants and where they are enforced

"DB" means a constraint in PostgreSQL. It still holds if the Python code has a bug or
someone writes to the database another way.

| Invariant | Enforced by |
|---|---|
| Consumption never goes over 480 | **DB**: `CHECK (0 <= consumed_minutes <= 480)` on `Quota`. **Domain**: the check happens under a row lock on the quota and returns `409 quota_exceeded` instead of hitting the constraint. |
| One decision per (request, role) | **DB**: `UNIQUE (request, role)` on `Decision`. **Domain**: checked under the request row lock and returns `409 invalid_state`. |
| Quota for a request is applied exactly once | **Domain**: minutes are only added on the `pending → approved` change, which happens while holding the request row lock. A second try sees `approved` and gets `409`. **DB**: the minutes are added in the same transaction as the `approved` event, and only one final event can exist per request, so a second application can't commit. |
| At most one final event per request | **DB**: partial unique index on `RequestEvent(request) WHERE event_type IN ('approved', 'rejected')`. |
| One quota row per employee and period | **DB**: `UNIQUE (employee, period)`. |
| Minutes between 1 and 480 | **DB**: `CHECK` on `QuotaRequest`. **API**: serializer validation gives a clear `400`. |
| `decided_at` is set exactly when a request is finished | **DB**: `CHECK` on `QuotaRequest`. |
| Period ends after it starts | **DB**: `CHECK (end_at > start_at)`. |
| Employees and managers have a team, HR may not | **DB**: `CHECK` on `User`. |
| Who can see and review what | **Domain**: `quotas/services/access.py` (`visible_requests`). Both the API and the decision service use it. |
| One idempotency key per user | **DB**: `UNIQUE (user, key)` on `IdempotencyKey`. |

The domain logic lives in `quotas/services/` and doesn't depend on HTTP. The views only
parse input and call services. Tests in `TestServiceWithoutHttp` call the services directly.

## Required decisions

### 1. Clock, and decisions after the period ends

- **"Now" comes from the application clock**, `utils/clock.py`, which returns Django's
  `timezone.now()` in UTC. Every place that needs the current time calls it. This gives one
  place to freeze time in tests, and app servers are expected to use NTP.
- **A request can be submitted while `now < end_at`.** The period is `[start_at, end_at)`,
  so at exactly `end_at` it is over. Submitting before `start_at` (a future period) is
  allowed.
- **Decisions after `end_at` are allowed.** The period end only stops new requests.
  Reviewers are often a few days late, and blocking them would leave requests stuck in
  `pending` forever.
- Tests: `test_period_end_is_exclusive`, `test_ended_period_returns_400`,
  `test_decision_after_period_end_is_allowed`, `test_decided_at_comes_from_the_app_clock`.

### 2. Where the quota record comes from

The `Quota` row is **created on demand inside the final approval transaction**. A pending
request doesn't need one. In `_lock_quota`:

1. `INSERT ... ON CONFLICT DO NOTHING` (Django's `bulk_create(ignore_conflicts=True)`). If
   two transactions do this at the same time, the unique index makes the second one wait
   for the first. It then does nothing instead of failing.
2. `SELECT ... FOR UPDATE` on the row, then check and update `consumed_minutes`.

So there can't be two rows (unique index) or more than 480 consumed (check constraint plus
the lock). When there's no row, `GET /quotas/{id}/` shows 0 consumed. The concurrency test
runs once with the row already there and once without it.

### 3. Shape of the final event

Event types in `RequestEvent`:

| Type | When | Final? |
|---|---|---|
| `submitted` | Request created | no |
| `decision_recorded` | Any successful decision | no |
| `approved` | Second approval succeeds | **yes** |
| `rejected` | Any rejection | **yes** |

**A rejected request also gets a final event**, so every finished request has exactly one,
whichever way it ended. The partial unique index allows at most one `approved` or
`rejected` event per request. A successful second approval writes `decision_recorded` and
then `approved`.

### 4. Approval and rejection at the same time

All decisions on one request lock the request row first (`SELECT ... FOR UPDATE`), so they
run one after the other. **Whoever gets the lock first goes first.** PostgreSQL queues lock
waiters in arrival order.

Both possible orders give a fixed, known result:

| Order | Final status | Decisions | Final events | Responses |
|---|---|---|---|---|
| Approve, then reject | `rejected` | 2 | 1 (`rejected`) | both `200`; approve shows `pending` |
| Reject, then approve | `rejected` | 1 | 1 (`rejected`) | reject `200`, approve `409 invalid_state` |

The final status is always `rejected`, there is always exactly one final event, and no quota
is used. A first approval can never finish a request, so a rejection always wins. The only
difference is whether the approval was recorded before the request closed. That depends on
which call arrived first, not on chance inside the code. Both orders are tested on purpose
in `TestApproveAndRejectAtOnce`.

### 5. When a manager or HR is the applicant

**Assumption for this version: managers and HR are not applicants.** Only users with the
`employee` role can submit (`403 forbidden` otherwise). This avoids the case where a
manager's own request would need a manager approval they can't give. The "can't review your
own request → 403" rule is still in the decision service.

If this is needed later, the simplest fix is that a manager's request is reviewed by another
manager of the team or by a higher manager, and HR's request by another HR user.

### 6. Idempotency details

Code: `utils/idempotency.py`, model `utils.models.IdempotencyKey`.

- **Scope.** A key belongs to one **user**. The **operation and target** are part of the
  fingerprint (method + path, for example `/requests/15/decisions/`). So the same key from
  two users is fine. The same key from one user on another route or another request gives
  `409 idempotency_key_reuse`.
- **Fingerprint.** SHA-256 of method, path and the **normalized JSON** body: the body is
  parsed and dumped again with sorted keys. Key order and whitespace don't change the
  meaning of the body, so they don't count as a different body.
- **Retention.** 24 hours (`IDEMPOTENCY_KEY_TTL_HOURS`). After that the key can be used for
  a new operation. Old keys are deleted when reused, or by `purge_expired`.
- **Which responses are stored.** Only final answers: `200, 201, 403, 404, 409`. These would
  be the same on retry. `400` is **not** stored, so the client can fix the body and retry
  with the same key. `5xx` is not stored either, so a retry after a crash really runs again.
  `401` and `429` happen before the idempotency code runs, so they are never stored.
- **Uniqueness in the database.** `UNIQUE (user, key)`. The code inserts the key first and
  only runs the operation if the insert worked. A duplicate insert fails with
  `IntegrityError`, and then we return the saved response.
- **Same key at the same time.** The key row, the operation and the saved response are all
  in **one transaction**. The second request's insert waits on the unique index until the
  first commits. Then it gets `IntegrityError` and replays the first response, with
  `Idempotent-Replayed: true`. If the first one ended with a response we don't store, its
  row is rolled back and the second one simply runs. Tested in
  `TestSameIdempotencyKeyAtOnce`.
- Because the key and the operation commit together, there is never a key without its
  side effect, or a side effect without its key.

### 7. Rate limit algorithm and policy

Code: `utils/ratelimit.py`.

- **Algorithm: fixed one-minute window.** A counter per user, per scope (read or write),
  per minute.
- **Store: Redis**, shared by all app processes. A counter in process memory is not used.
- **Key:** `ratelimit:{read|write}:user:{user_id}:{minute_number}`. Calls without a login
  (the login endpoint itself) use `ip:{client_ip}` instead of the user, so passwords can't be
  guessed without a limit. `NUM_PROXIES = 0` makes DRF use the real connection IP and ignore
  `X-Forwarded-For`, which a client could fake.
- **Counting:** `INCR` and `EXPIRE` (2 minutes, just for cleanup) are sent in one Redis
  transaction, so it's one round trip and two processes can never lose a hit. I checked
  this with two server processes and 200 parallel requests: exactly 120 got through and
  80 got `429`.
- **Limits:** 30 writes and 120 reads per minute by default (`RATE_LIMIT_WRITE_PER_MINUTE`,
  `RATE_LIMIT_READ_PER_MINUTE`). Over the limit: `429 rate_limited` with `Retry-After` set
  to the seconds until the next minute starts.
- **Why a fixed window.** It costs one atomic Redis call and one small key per user per
  minute, and it is easy to explain to a user ("try again in N seconds"). The downside: a
  user can send up to twice the limit around a minute boundary. For limits meant to stop
  abuse, not to bill anyone, that's fine. A sliding window or token bucket would be smoother
  but needs a Lua script or more keys.
- **Replays are counted.** The limiter runs before the view, so every HTTP call counts,
  including idempotent replays and calls that end in `400`. A replay still costs a request
  to serve, and a client stuck in a retry loop should be slowed down too.
- **Fail open.** If Redis is down, the request is let in and a warning is logged. Redis has
  a 0.5 second timeout, so an outage doesn't make requests slow. The reason: the limiter
  protects the service, it doesn't protect correctness. All quota rules are enforced by
  PostgreSQL, so letting extra requests in can't break the data. Failing closed would turn a
  Redis outage into a full API outage.
- Tests don't sleep. They freeze the app clock and move it forward (`TestRateLimit`).

### 8. Locks, lock order and isolation

- **Isolation level:** PostgreSQL's default, **READ COMMITTED**. Correctness comes from
  explicit row locks, not from the isolation level.
- **Locks:** `SELECT ... FOR UPDATE` on the request row, then on the quota row.
- **Lock order is always the same:**
  1. The idempotency key row (unique index insert)
  2. The request row
  3. The quota row (only on a final approval)

  Every transaction takes locks in this order, so two of them can't wait on each other in a
  circle. That means no deadlocks in these flows.
- **After waiting for a lock, the code re-reads the row.** In READ COMMITTED,
  `SELECT FOR UPDATE` returns the newest committed version. So the loser sees the real
  status or consumption and gets a normal domain answer: `409 quota_exceeded` or
  `409 invalid_state`. It never gets a 500.
- **Serialization failures** can't happen in READ COMMITTED. If a deadlock ever did happen
  (for example, from code added later), PostgreSQL would cancel one transaction. The client
  would get a `500`, which is not stored for idempotency, so retrying with the same key is
  safe.

### 9. Pagination and sort order

- **Page-number (offset) pagination**: `?page=2&page_size=50`. Default page size is 20,
  maximum is 100. Larger values are cut to 100. A page past the end returns `404`.
- **Order:** newest first, `created_at DESC, id DESC`. `id` breaks ties, so the order is
  stable even when two requests have the same timestamp. There is an index on
  `(created_at DESC, id DESC)`.
- **Why offset:** it is simple, gives a total `count`, and the data per user is small.
  Keyset (cursor) pagination would be better for very large tables or deep pages, because it
  doesn't skip rows and doesn't shift when new rows come in. DRF's `CursorPagination` could
  replace it without changing anything else.

### 10. Notification after final approval

Not implemented. Here is how I would build it:

- **If the database commits but sending fails, how is the message not lost?** Use a
  transactional outbox. In the same transaction that approves the request, insert a row
  into a `notification_outbox` table. The `approved` event row could also be used for this.
  A background worker reads unsent rows, sends them, and marks them sent. If sending or
  queueing fails, the row stays unsent and the worker tries again later. The message can't
  get lost, because it was committed together with the approval. Sending straight from the
  request, or from `transaction.on_commit`, can lose it if the process dies at the wrong
  moment.
- **If delivery is repeated, how is a duplicate effect prevented?** The outbox gives
  at-least-once delivery, so duplicates are expected. Every message carries the outbox row
  id (or event id) as its idempotency key. The receiver keeps the ids it has already
  handled, with a unique constraint, and ignores repeats. If the external service supports
  idempotency keys, we pass the same id to it.

### Log

Every status change and every successful decision writes a `RequestEvent` row with the
actor, the time, the event type and the request id. It is written **in the same transaction
as the change**, so a change can't happen without its log row.

- **Failed attempts (403, 404, 409) are not logged.** So the log can't reveal that a hidden
  request exists.
- The `reason` text is only returned by the request list and detail endpoints, to users who
  are allowed to see that request. It is never written to the operational log or included in
  decision responses or errors. Tokens are never logged. The only operational log line is a
  warning when Redis is down, and it contains no user data.

## Tests

```bash
docker compose up -d     # tests need the real PostgreSQL and Redis
uv run pytest            # all tests
uv run pytest quotas/tests/test_concurrency.py -v   # only the concurrency tests
```

pytest-django creates a separate test database (`test_quota_manager`) in the same
PostgreSQL. Tests use Redis database 15 and clear it before each test. SQLite is not used
anywhere.

| File | What it covers |
|---|---|
| `accounts/tests/test_models.py` | User and team constraints |
| `accounts/tests/test_auth.py` | JWT and token login, 401 cases |
| `quotas/tests/test_models.py` | Database constraints behind each invariant |
| `quotas/tests/test_requests_api.py` | Submitting, validation, visibility per role, 404 vs 403, filters, pagination, ordering |
| `quotas/tests/test_decisions.py` | Every row of the decision table, the event log, clock rules, services without HTTP, quota summary |
| `quotas/tests/test_idempotency.py` | Missing key, replay, key reuse, which responses are stored, retention |
| `quotas/tests/test_ratelimit.py` | 429 threshold, `Retry-After`, window reopening, replays counted, fail open |
| `quotas/tests/test_concurrency.py` | Real concurrent transactions on PostgreSQL |
| `quotas/tests/test_seed.py` | Sample data command |
| `utils/tests/test_errors.py` | JSON errors for wrong URLs, missing trailing slash and crashes |

### How the concurrency tests create overlap

The tests in `test_concurrency.py` use real threads. Each thread has its own PostgreSQL
connection, and the tests don't sleep and hope:

1. A "holder" thread opens a transaction and locks the row both workers will need. In the
   300 + 300 case that's the quota row, and in the duplicate approval case it's the request
   row. In the "no quota row yet" case, the holder inserts the quota row and doesn't commit.
2. Two worker threads send their HTTP requests through the full stack: auth, rate limit,
   idempotency and service.
3. The test polls `pg_stat_activity` until PostgreSQL reports **two sessions waiting on a
   lock**. At that point both transactions are open at the same time, for certain.
4. The holder commits, and PostgreSQL lets the workers through one at a time.
5. The test checks both HTTP responses and the database: status, consumed minutes, number
   of decisions and number of final events.

When the test needs a fixed order (approve-then-reject vs reject-then-approve), it starts
worker 2 only after worker 1 is already waiting. PostgreSQL queues lock waiters in arrival
order.

I checked that these tests really catch bugs: removing `select_for_update()` from the quota
lock makes the 300 + 300 test fail, with both approvals returning 200.

## Assumptions

- Managers and HR don't submit requests. See decision 5.
- Nobody is both a manager and HR. A user has exactly one role.
- A manager can review any request from their own team. If a team has two managers, the
  first manager decision counts for the "manager" role.
- HR has no team.
- Periods and users are created with `seed` or the Django admin. There is no API for them,
  as the task says this is out of scope.
- In the Django admin, requests, decisions, events, quotas and idempotency keys are
  **view only**. Editing them by hand would skip the locks, the quota check and the event
  log, so they only change through the API.
- Requests can't be cancelled by the applicant. This is also out of scope.

## Limitations and what I would do next

- **Notification** is designed (decision 10) but not built.
- **Replays don't keep response headers**, only the status and body. Our endpoints don't
  return special headers, so nothing is lost today.
- **The idempotency transaction stays open while the operation runs.** That's fine here,
  because the operations only touch the database. If a decision ever calls an external
  service, I would switch to an "in progress" key that is committed first, and return
  `409` to a duplicate that arrives meanwhile.
- **A duplicate request with the same key waits with no time limit.** Setting PostgreSQL's
  `lock_timeout` would cap that.
- **Fixed window rate limit** allows short bursts at minute boundaries (decision 7).
- **Offset pagination** gets slow on very deep pages (decision 9).
- **No automatic deadlock retry.** The fixed lock order should prevent deadlocks. If one
  happens, the client gets a `500` and can safely retry with the same key.
