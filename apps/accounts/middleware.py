from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class Require2FAMiddleware:
    """Send users whose role is listed in RENTMASTER["REQUIRE_2FA_ROLES"] to the
    2FA setup page until they have enabled it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        roles = settings.RENTMASTER.get("REQUIRE_2FA_ROLES", ())
        if user is not None and user.is_authenticated and user.role in roles and not user.totp_enabled:
            allowed = (reverse("two_factor_setup"), reverse("logout"))
            if request.path not in allowed:
                return redirect("two_factor_setup")
        return self.get_response(request)
