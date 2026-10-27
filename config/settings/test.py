"""Settings for the test suite. Still PostgreSQL — the concurrency tests need it."""

from .base import *  # noqa: F403

DEBUG = False

# Fast hashing; test passwords are fake and never secret.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Tests use their own Redis database, so clearing it never touches dev data.
CACHES["default"]["LOCATION"] = env("TEST_REDIS_URL", default="redis://localhost:6380/15")  # noqa: F405
