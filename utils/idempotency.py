import hashlib
import json
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.db import transaction
from rest_framework.response import Response

from utils import clock
from utils.errors import IdempotencyKeyMissing, IdempotencyKeyReuse, IdempotencyKeyTooLong
from utils.models import IdempotencyKey

# Only final answers are saved. 400 and 5xx are not, so the client can fix the
# request or try again with the same key.
STORED_STATUSES = {200, 201, 403, 404, 409}


def fingerprint(request):
    body = json.dumps(request.data, sort_keys=True)
    return hashlib.sha256(f"{request.method} {request.path} {body}".encode()).hexdigest()


def idempotent(view_method):
    @wraps(view_method)
    def wrapper(view, request, *args, **kwargs):
        key = request.headers.get("Idempotency-Key")
        if not key:
            raise IdempotencyKeyMissing()
        if len(key) > 255:
            raise IdempotencyKeyTooLong()

        request_fingerprint = fingerprint(request)

        with transaction.atomic():
            # Forget the key if it's too old, so it can be used again.
            expired = clock.now() - timedelta(hours=settings.IDEMPOTENCY_KEY_TTL_HOURS)
            IdempotencyKey.objects.filter(user=request.user, key=key, created_at__lt=expired).delete()

            # The (user, key) pair is unique. If another request with this key is
            # still running, this waits until it finishes, then returns its row.
            record, created = IdempotencyKey.objects.get_or_create(
                user=request.user,
                key=key,
                defaults={"fingerprint": request_fingerprint, "created_at": clock.now()},
            )

            # Seen this key before: send back the saved answer.
            if not created:
                if record.fingerprint != request_fingerprint:
                    raise IdempotencyKeyReuse()
                return Response(record.response_body, record.response_status, headers={"Idempotent-Replayed": "true"})


            try:
                response = view_method(view, request, *args, **kwargs)
            except Exception as exc:
                response = view.handle_exception(exc)

            if response.status_code in STORED_STATUSES:
                record.response_status, record.response_body = response.status_code, response.data
                record.save()
            else:
                transaction.set_rollback(True)  # don't keep the key
            return response

    return wrapper
