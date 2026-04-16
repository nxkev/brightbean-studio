"""API key authentication for the REST API."""

import hashlib
import secrets

from django.conf import settings
from django.http import JsonResponse


def generate_api_key():
    """Generate a new API key."""
    return "bb_" + secrets.token_urlsafe(32)


def hash_api_key(key):
    """Hash an API key for storage."""
    return hashlib.sha256(key.encode()).hexdigest()


def api_auth_required(view_func):
    """Decorator that requires a valid API key in the Authorization header.

    Usage: Authorization: Bearer bb_xxxx
    """

    def wrapper(request, *args, **kwargs):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return JsonResponse(
                {"error": "Missing or invalid Authorization header. Use: Bearer <api_key>"},
                status=401,
            )

        api_key = auth_header[7:].strip()
        valid_key = getattr(settings, "API_KEY", "")
        if not valid_key or api_key != valid_key:
            return JsonResponse({"error": "Invalid API key"}, status=401)

        return view_func(request, *args, **kwargs)

    return wrapper
