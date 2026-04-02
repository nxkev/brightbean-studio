from django.shortcuts import redirect
from django.urls import reverse

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
