import hashlib

from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

# Paths that are rate-limited for unauthenticated POST requests (auth flows)
AUTH_RATE_LIMITED_PATHS = (
    "/accounts/login/",
    "/accounts/signup/",
    "/accounts/password/reset/",
    "/accounts/password/reset/key/",
)

# Rate limit: 10 POST requests per minute per IP for auth endpoints
AUTH_RATE_LIMIT = 10
AUTH_RATE_WINDOW = 60  # seconds

EXEMPT_PATH_PREFIXES = (
    "/accounts/accept-terms/",
    "/accounts/logout/",
    "/accounts/google/",
    "/accounts/3rdparty/",
    "/health/",
    "/static/",
    "/admin/",
)


class TosAcceptanceMiddleware:
    """Redirect authenticated users to the ToS acceptance page if they haven't accepted yet."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            hasattr(request, "user")
            and request.user.is_authenticated
            and request.user.tos_accepted_at is None
            and not request.path.startswith(EXEMPT_PATH_PREFIXES)
        ):
            return redirect(reverse("accounts:accept_terms"))

        return self.get_response(request)


class AuthRateLimitMiddleware:
    """Rate-limit POST requests to authentication endpoints (login, signup, password reset)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and any(request.path.startswith(p) for p in AUTH_RATE_LIMITED_PATHS):
            ip = self._get_client_ip(request)
            cache_key = f"auth_ratelimit:{hashlib.md5(ip.encode()).hexdigest()}"

            if self._is_shared_cache():
                # Redis or another shared cache — safe across workers
                attempts = cache.get(cache_key, 0)
                if attempts >= AUTH_RATE_LIMIT:
                    return HttpResponse("Too many requests. Please try again later.", status=429)
                cache.set(cache_key, attempts + 1, AUTH_RATE_WINDOW)
            else:
                # LocMemCache is per-process — use database for cross-worker accuracy
                if self._db_rate_limit_exceeded(cache_key):
                    return HttpResponse("Too many requests. Please try again later.", status=429)

        return self.get_response(request)

    @staticmethod
    def _is_shared_cache():
        """Check if the default cache backend is shared across processes."""
        backend = cache.__class__.__module__ + "." + cache.__class__.__name__
        return "locmem" not in backend.lower()

    @staticmethod
    def _db_rate_limit_exceeded(cache_key):
        """Database-backed rate limit check using django_session table pattern.

        Uses a lightweight SQL approach that works across all gunicorn workers.
        """
        from django.utils import timezone as tz
        from datetime import timedelta

        window_start = tz.now() - timedelta(seconds=AUTH_RATE_WINDOW)

        with connection.cursor() as cursor:
            # Create rate limit table if it doesn't exist (idempotent)
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS auth_rate_limit (
                    cache_key VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            # Purge expired entries
            cursor.execute("DELETE FROM auth_rate_limit WHERE created_at < %s", [window_start])
            # Count recent attempts
            cursor.execute(
                "SELECT COUNT(*) FROM auth_rate_limit WHERE cache_key = %s AND created_at >= %s",
                [cache_key, window_start],
            )
            count = cursor.fetchone()[0]
            if count >= AUTH_RATE_LIMIT:
                return True
            # Record this attempt
            cursor.execute(
                "INSERT INTO auth_rate_limit (cache_key, created_at) VALUES (%s, %s)",
                [cache_key, tz.now()],
            )
        return False

    @staticmethod
    def _get_client_ip(request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")
