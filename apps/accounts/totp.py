"""RFC 6238 time-based one-time passwords (Google Authenticator, Microsoft
Authenticator, Authy...). Standard library only."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10 ** DIGITS:0{DIGITS}d}"


def current_code(secret, at=None):
    return _code(secret, int((at or time.time()) // STEP))


def verify(secret, code, at=None, window=1):
    """Accept the current code and one step either side for clock drift."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if not secret or len(code) != DIGITS:
        return False
    counter = int((at or time.time()) // STEP)
    return any(hmac.compare_digest(_code(secret, counter + d), code) for d in range(-window, window + 1))


def provisioning_uri(secret, username, issuer="RENTMASTER"):
    return (f"otpauth://totp/{quote(issuer)}:{quote(username)}?secret={secret}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}")
