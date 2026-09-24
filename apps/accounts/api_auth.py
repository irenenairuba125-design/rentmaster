"""Token login for the mobile app.

    POST /api/auth/login/   {"username", "password", "code"?, "device"?}
        -> 200 {"token", "expires_at", "user": {...}}
        -> 401 {"detail", "two_factor_required": true}   when a 2FA code is needed
        -> 429 after too many failed attempts
    Send the token as:  Authorization: Bearer <token>
    POST /api/auth/logout/  revokes the token used for the request.
"""
import secrets
from datetime import timedelta

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core.audit import log_action

from . import totp
from .authentication import hash_key
from .models import ApiToken

TOKEN_LIFETIME = timedelta(days=30)
MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60


def issue_token(user, device=""):
    key = secrets.token_urlsafe(32)
    token = ApiToken.objects.create(user=user, key_hash=hash_key(key), device=device[:100],
                                    expires_at=timezone.now() + TOKEN_LIFETIME)
    return key, token


def _fail_key(username):
    return f"rm-api-login-fail:{username.lower()}"


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def api_login(request):
    username = str(request.data.get("username", "")).strip()
    password = str(request.data.get("password", ""))
    key = _fail_key(username)
    if cache.get(key, 0) >= MAX_FAILURES:
        return Response({"detail": "Too many failed attempts. Try again in 15 minutes."},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)

    user = authenticate(request, username=username, password=password)
    if user is not None and user.totp_enabled:
        code = request.data.get("code")
        if not code:
            # Correct password: ask for the code without counting a failure.
            return Response({"detail": "Two-factor code required.", "two_factor_required": True},
                            status=status.HTTP_401_UNAUTHORIZED)
        if not totp.verify(user.totp_secret, code):
            user = None
    if user is None:
        cache.set(key, cache.get(key, 0) + 1, LOCKOUT_SECONDS)
        return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

    cache.delete(key)
    raw, token = issue_token(user, str(request.data.get("device", "")))
    log_action(f"Mobile app sign-in ({token.device or 'unknown device'})", user, user=user)
    return Response({
        "token": raw,
        "expires_at": token.expires_at,
        "user": {"username": user.username, "name": str(user), "role": user.role},
    })


@api_view(["POST"])
def api_logout(request):
    if isinstance(request.auth, ApiToken):
        request.auth.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
