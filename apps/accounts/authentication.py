"""Bearer-token authentication for the mobile app. Kept apart from the login views:
DRF imports this module while it is still loading its own views."""
import hashlib
from datetime import timedelta

from django.utils import timezone
from rest_framework import authentication, exceptions


def hash_key(key):
    return hashlib.sha256(key.encode()).hexdigest()


class BearerTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        from .models import ApiToken

        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Invalid Authorization header.")
        token = ApiToken.objects.select_related("user").filter(key_hash=hash_key(header[1].decode(errors="ignore"))).first()
        if token is None or token.expires_at <= timezone.now() or not token.user.is_active:
            raise exceptions.AuthenticationFailed("Invalid or expired token.")
        now = timezone.now()
        if not token.last_used_at or now - token.last_used_at > timedelta(minutes=5):
            ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)
        return token.user, token

    def authenticate_header(self, request):
        return self.keyword
