import logging

import redis
from django.conf import settings
from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import BaseThrottle

from utils import clock

logger = logging.getLogger(__name__)

# One client per process, shared by all threads. The short timeout means a
# broken Redis can't make requests slow.
redis_client = redis.Redis.from_url(settings.CACHES["default"]["LOCATION"], socket_timeout=0.5)


class RateThrottle(BaseThrottle):
    """Counts requests in Redis, per user (or per IP when not logged in), per minute."""

    def allow_request(self, request, view):
        if request.method in SAFE_METHODS:
            scope, limit = "read", settings.RATE_LIMIT_READ_PER_MINUTE
        else:
            scope, limit = "write", settings.RATE_LIMIT_WRITE_PER_MINUTE

        who = f"user:{request.user.pk}" if request.user.is_authenticated else f"ip:{self.get_ident(request)}"
        minute, second = divmod(int(clock.now().timestamp()), 60)
        self.retry_after = 60 - second
        key = f"ratelimit:{scope}:{who}:{minute}"

        try:
            # INCR and EXPIRE are sent together and run as one step, so no hit
            # is lost even when many processes count at the same time.
            count, _ = redis_client.pipeline().incr(key).expire(key, 120).execute()
        except redis.RedisError:
            logger.warning("Rate limit store unavailable, allowing request")
            return True  # fail open

        return count <= limit

    def wait(self):
        return self.retry_after
