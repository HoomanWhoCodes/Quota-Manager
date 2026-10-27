# Quota Manager

Backend for employee request quotas. Every employee has 480 minutes per period. A request
needs two approvals, one from the team manager and one from HR. The minutes are taken from
the quota when the second approval goes through. One rejection ends the request.

Django + Django REST Framework, PostgreSQL and Redis.

## Versions

- Python 3.13.7, uv 0.12.17
- Django 5.2.18, Django REST Framework 3.18.3, djangorestframework-simplejwt 5.5.1
- django-environ 0.14.0, psycopg 3.3.6, redis (Python client) 8.1.0
- pytest 9.1.1, pytest-django 4.14.0
- PostgreSQL 17 (tested on 17.10), Redis 8 (tested on 8.10.2), both from Docker images

## Running it

You need Docker and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env
docker compose up -d
uv sync
uv run python manage.py migrate
uv run python manage.py seed
uv run python manage.py runserver
```

Postgres runs on port 5433 and Redis on 6380, so they don't clash with ones you may already
have. Everything in `.env.example` is fake and only for local use.

### Sample data

```bash
uv run python manage.py seed
```

This makes a period that starts today and lasts 30 days, so it's always open when you run it,
plus these users. Running it again is safe. `seed --reset` also deletes all requests, quotas,
idempotency keys and rate limit counters, if you want to start clean.

The passwords and tokens are fake and only for local testing.

| User  | Role          | Team        | Password    | Token              |
| ----- | ------------- | ----------- | ----------- | ------------------ |
| alice | employee      | Engineering | password123 | `alice-fake-token` |
| bob   | employee      | Engineering | password123 | `bob-fake-token`   |
| maria | manager       | Engineering | password123 | `maria-fake-token` |
| sam   | manager       | Sales       | password123 | `sam-fake-token`   |
| hana  | hr            | -           | password123 | `hana-fake-token`  |
| admin | hr, superuser | -           | password123 | `admin-fake-token` |

sam is there so you can see the `404` a manager of another team gets. admin is for the Django
admin at `/admin/`. The command refuses to run with `DEBUG` off, because the passwords are
fake (`--force` overrides that).

Each user has one role: `employee`, `manager` or `hr`. Employees and managers need a team, HR
doesn't. The database checks this, which is why plain `createsuperuser` fails (it tries to
make an employee with no team). The admin user is HR for that reason.

### Cleaning up old idempotency keys

```bash
uv run python manage.py purge_expired
```

In production this would be a cron job. It's only cleanup: an expired key is also deleted
when someone uses it again.

## Logging in

- JWT: `POST /api/v1/auth/token/` with username and password gives you `access` and
  `refresh`. Send `Authorization: Bearer <access>`. Access tokens last 15 minutes, refresh
  tokens 1 day. `POST /api/v1/auth/token/refresh/` gives a new access token.
- Static token, handy for testing: `Authorization: Token <key>`. `seed` makes one for every
  user, like `alice-fake-token`.

Everything except login needs one of these, otherwise you get `401`.

## API

All routes start with `/api/v1/` and end with `/`. There's no redirect for a missing slash,
because a redirect would drop the body of a POST.

- `POST /requests/` with `period_id`, `minutes` (1 to 480) and `reason`. Employees only.
  Returns `201` and the request as `pending`.
- `GET /requests/` lists requests. Employees see their own, managers their team's, HR sees
  all. Filter with `status` and `period_id`, page with `page` and `page_size`.
- `GET /requests/{id}/` shows one request with its decisions.
- `POST /requests/{id}/decisions/` with `{"decision": "approve"}` or `"reject"`. Returns the
  decision and the new status of the request.
- `GET /quotas/{period_id}/` shows your own ceiling, used and remaining minutes. You can't
  ask for someone else's.
- `GET /periods/` lists periods with an `is_open` flag. Not in the task, I added it so a
  client can find the open period.

Both POST endpoints need an `Idempotency-Key` header.

### Example

Log in as alice:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "password123"}'
```

```json
{"refresh": "eyJhbGciOi...", "access": "eyJhbGciOi..."}
```

Submit a request with her access token:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/requests/ \
  -H "Authorization: Bearer $ALICE" \
  -H "Idempotency-Key: 6f1c2a9e-3b7d-4e0f-9a51-2c8d4b6e1f70" \
  -H "Content-Type: application/json" \
  -d '{"period_id": 1, "minutes": 120, "reason": "Dentist appointment"}'
```

```json
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

If you send the exact same call again, you get the same response back with an
`Idempotent-Replayed: true` header, and nothing new is created.

After maria approves, hana approves too:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/requests/15/decisions/ \
  -H "Authorization: Bearer $HANA" \
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

Now alice's quota for the period shows 120 used and 360 left.

## Errors

Every error looks like this:

```json
{"error": {"code": "not_found", "message": "Not found.", "details": null}}
```

`details` is only filled for validation errors. Wrong URLs and crashes use the same shape
(with `DEBUG` on you get Django's debug page instead).

| Status | Code                        | When                                                               |
| ------ | --------------------------- | ------------------------------------------------------------------ |
| 400    | `validation_error`        | Bad input, unknown or ended period, key longer than 255 characters |
| 400    | `idempotency_key_missing` | No `Idempotency-Key` header                                      |
| 401    | `not_authenticated`       | Not logged in, or bad token                                        |
| 403    | `forbidden`               | Reviewing your own request, or a manager or HR trying to submit    |
| 404    | `not_found`               | Doesn't exist, or you're not allowed to see it                     |
| 409    | `invalid_state`           | Your role already decided, or the request is already finished      |
| 409    | `idempotency_key_reuse`   | Same key with a different body or URL                              |
| 409    | `quota_exceeded`          | Second approval but not enough minutes left                        |
| 429    | `rate_limited`            | Too many requests, see `Retry-After`                             |
| 500    | `server_error`            | A bug                                                              |

A request you're not allowed to see gives exactly the same 404 as one that doesn't exist, so
you can't find out whether it's there.

## Where each rule is enforced

I tried to put the important rules in the database, so they hold even if the Python code has
a bug.

- Used minutes never go over 480: a `CHECK` constraint on `Quota`. The service also checks it
  while holding a lock on the quota row and returns `409 quota_exceeded`, so the constraint is
  only a safety net.
- One decision per request and role: a unique constraint on `(request, role)`. The service
  checks it first and returns `409 invalid_state`.
- The quota is used only once per request: minutes are added only when a request moves from
  `pending` to `approved`, and that happens while the request row is locked. They're added in
  the same transaction as the `approved` event, and the database allows only one final event
  per request, so a second attempt can't commit.
- At most one final event per request: a partial unique index on `RequestEvent(request)` for
  the `approved` and `rejected` types.
- Also in the database: one quota row per employee and period, minutes between 1 and 480,
  `decided_at` set exactly when a request is finished, periods ending after they start,
  employees and managers having a team, and one idempotency key per user.
- Who can see what is in the service layer (`quotas/services/access.py`). The list, the
  detail page and decisions all use the same function.

The business logic lives in `quotas/services/` and doesn't know about HTTP, so it's safe to
call from anywhere, not just the API. Some tests call it directly.

## Decisions

### Clock and the end of a period

The current time comes from `utils/clock.py` (Django's `timezone.now()`, in UTC), not from the
database. That gives me one place to freeze time in tests.

A period is `[start_at, end_at)`, so you can submit while `now < end_at`. Decisions are still
allowed after the period ends. Reviewers are sometimes late, and I didn't want requests stuck
in `pending` forever.

### The quota row

It's created when it's first needed, inside the final approval. I insert it with
`ON CONFLICT DO NOTHING`, then lock it with `SELECT ... FOR UPDATE`. If two approvals do this
at once, the unique index makes the second one wait and then do nothing, so there's never a
second row and never a crash. Before the first approval the quota simply shows 0 used.

### Events

Event types are `submitted`, `decision_recorded`, `approved` and `rejected`. The last two are
the final events. A rejected request gets one too, so every finished request has exactly one,
however it ended.

### Approve and reject at the same time

Every decision locks the request row first, so decisions on one request run one after
another, in the order they arrive. Either way the request ends up `rejected` with one final
event and no minutes used:

- approve first: the approval is saved (still `pending`), then the rejection finishes it. Two
  decisions, both `200`.
- reject first: the request is finished, and the approval gets `409 invalid_state`. One
  decision.

The only difference is whether the approval got in before the request closed. Both orders
are tested.

### Managers and HR as applicants

In this version only employees can submit, and managers or HR get `403`. Otherwise a
manager's own request would need a manager approval they can't give themselves. The "you
can't review your own request" rule is still there. If this were needed later, another
manager (or HR user) would review it.

### Idempotency

- A key belongs to one user. The method and URL are part of what's compared, so one key can't
  be used for two different requests or two different targets.
- I compare a SHA-256 of the method, the path and the JSON body re-dumped with sorted keys, so
  key order and spacing don't matter.
- Keys are kept for 24 hours (`IDEMPOTENCY_KEY_TTL_HOURS`).
- I save responses with status 200, 201, 403, 404 and 409, since retrying would give the same
  answer anyway. 400 isn't saved, so the client can fix the body and retry with the same key.
  5xx isn't saved, so a retry really runs again. 401 and 429 happen before this code runs.
- The database has a unique constraint on `(user, key)`. I save the key, run the operation
  and save the response in one transaction. If a second request with the same key arrives
  while the first is still running, it waits on that unique index, then gets the saved
  response. If the first one wasn't saved (a 400 for example), the second one just runs.

### Rate limiting

- Fixed one-minute window: 30 writes and 120 reads per minute per user, set with
  `RATE_LIMIT_WRITE_PER_MINUTE` and `RATE_LIMIT_READ_PER_MINUTE`. Over the limit you get `429`
  with `Retry-After`.
- The counters live in Redis, so all app processes share them. The key is
  `ratelimit:{read|write}:user:{id}:{minute}`. `INCR` and `EXPIRE` go to Redis in one
  transaction, so no hit is lost when several processes count at once. With two server
  processes and 200 parallel requests, exactly 120 got through.
- When nobody is logged in (that's only the login endpoint) I count per IP instead, so nobody
  can try passwords without a limit. `NUM_PROXIES = 0` makes DRF use the real IP and ignore
  `X-Forwarded-For`, which anyone can fake.
- I picked a fixed window because it's one cheap Redis call per request and it's easy to
  tell the user when to come back. The downside is that someone can send up to twice the limit
  around the edge of a minute. For a limit that's there to stop abuse, I think that's fine.
- Replays count against the limit. The limiter runs before the view, and a client stuck in a
  retry loop should be slowed down too.
- If Redis is down, requests are let through and a warning is logged (fail open). The limiter
  protects the server, not the data. All the quota rules are in PostgreSQL, so extra requests
  can't break anything, while failing closed would take the whole API down with Redis.

### Locks and isolation

I use PostgreSQL's default isolation, READ COMMITTED, with explicit row locks
(`SELECT ... FOR UPDATE`). Locks are always taken in the same order: the idempotency key, then
the request row, then the quota row. Since every transaction follows that order, they can't
deadlock each other.

After waiting for a lock, PostgreSQL gives back the latest version of the row, so whoever
loses the race sees the real state and gets a normal answer (`409 quota_exceeded` or
`409 invalid_state`), not a 500.

### Pagination

Page numbers: `?page=2&page_size=50`. The default page size is 20 and the max is 100. Lists
are sorted newest first by `created_at`, then `id`, so the order is stable even when two
requests have the same time. I went with page numbers because they're simple and the lists
are small. For big tables I'd switch to cursor pagination.

### Notification after approval

I didn't build it. I'd use Celery with Redis as the queue, plus a `notified_at` column on
the request.

**How is the message not lost if sending fails?**

- After the approval commits, `transaction.on_commit` puts a Celery task in the Redis queue.
  The task sends the message and then sets `notified_at`.
- If sending fails, Celery retries the task.
- A Celery task can still be lost if Redis is down or the process dies right after the commit,
  before the task is queued. So a Celery beat job runs every minute and queues a task for every
  approved request that still has `notified_at` empty. The approval is saved in the database,
  so it can always be found and sent later.

**How is a duplicate prevented if the message is sent twice?**

- A task can run twice: a retry after a timeout, or the beat job queueing a request that is
  already being sent.
- The task works in one transaction. It locks the request row only if it's not sent yet
  (`SELECT ... FOR UPDATE SKIP LOCKED` with `notified_at IS NULL`). If it gets no row, another
  task already sent it or is sending it right now, so it stops.
- If it gets the row, it sends the message, sets `notified_at` and commits. If sending fails,
  the transaction rolls back, `notified_at` stays empty, and the message is retried later.
- One gap is left: the process could die after sending but before the commit. Then the message
  goes out again. To cover that, we pass the request id as an idempotency key to the email or
  SMS service, if it supports one, so it ignores the second copy.

### Logs

Every status change and every successful decision writes a `RequestEvent` (who, when, what,
which request) in the same transaction as the change. Failed attempts (403, 404, 409) aren't
logged, so the log can't reveal a request someone isn't allowed to see. The `reason` text only
shows up in the request list and detail for people who can see that request, and tokens are
never logged.

## Tests

```bash
docker compose up -d
uv run pytest
```

The tests run on a separate PostgreSQL test database and a separate Redis database (15),
never SQLite. They cover the decision table, who can see what, idempotency, rate limiting,
errors, pagination and the database constraints. No test sleeps: time-based tests move a
frozen clock instead.

### Concurrency tests

`quotas/tests/test_concurrency.py` runs real threads, each with its own database connection,
for the 300 + 300 case, a double final approval, the same idempotency key twice at once, and
approve vs reject.

To make sure the two transactions really overlap, a third connection first locks the row
both of them need. Then both requests are sent, and the test waits until PostgreSQL's
`pg_stat_activity` shows both of them blocked on that lock. Only then is the lock released.
After that the test checks the responses and the database.

When I removed `select_for_update()` from the quota code, the 300 + 300 test failed with both
approvals returning 200, so the tests do catch the bug they're meant to catch.

## Assumptions

- Only employees submit requests. Nobody is both manager and HR.
- If a team has two managers, either one can give the manager decision, but only one counts.
- HR users have no team.
- Users and periods come from `seed` or the Django admin. There's no API for them (the task
  leaves that out).
- In the admin, requests, decisions, quotas, events and idempotency keys are read-only, because
  changing them by hand would skip the locks and checks.
- Applicants can't cancel requests (out of scope).

## What's missing

- The idempotency transaction stays open while the request is handled. That's fine while
  everything happens in the database, but if a decision ever called an outside service, I'd
  save an "in progress" key first and return `409` to a duplicate that arrives in between.
- A duplicate request with the same key waits with no time limit. A `lock_timeout` would fix
  that.
- There's no automatic retry on deadlocks. The fixed lock order should prevent them, and if
  one happens the client gets a 500 and can safely retry with the same key.
