from uuid import uuid4

REQUESTS_URL = "/api/v1/requests/"


def detail_url(request_id):
    return f"{REQUESTS_URL}{request_id}/"


def decide_url(request_id):
    return f"{REQUESTS_URL}{request_id}/decisions/"


def quota_url(period_id):
    return f"/api/v1/quotas/{period_id}/"


def post(client, url, data, key=None):
    """POST with an Idempotency-Key. A new random key is used unless one is given."""
    return client.post(url, data, format="json", headers={"Idempotency-Key": key or str(uuid4())})


def submit(client, period_id, minutes=60, reason="Doctor visit", key=None):
    return post(client, REQUESTS_URL, {"period_id": period_id, "minutes": minutes, "reason": reason}, key)


def decide(client, request_id, decision, key=None):
    return post(client, decide_url(request_id), {"decision": decision}, key)


def error_code(response):
    return response.json()["error"]["code"]
