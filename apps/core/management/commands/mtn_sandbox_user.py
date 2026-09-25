"""Create MTN MoMo **sandbox** (test) credentials from your subscription key.

1. Sign up at https://momodeveloper.mtn.com, subscribe to the "Collections"
   product and copy its Primary Key.
2. python manage.py mtn_sandbox_user --subscription-key <PRIMARY KEY> --host rentmaster-chi.vercel.app
3. Paste the printed variables into Vercel (Settings -> Environment Variables).

Sandbox payments are simulated by MTN: no real money moves. For real money, MTN
issues production credentials after you complete their go-live (KYC) process.
"""
import json
import urllib.error
import urllib.request
import uuid

from django.core.management.base import BaseCommand, CommandError

SANDBOX = "https://sandbox.momodeveloper.mtn.com"


def _post(url, headers, body=None):
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode() or "{}"
            return json.loads(text) if text.strip().startswith("{") else {}
    except urllib.error.HTTPError as exc:
        raise CommandError(f"MTN returned HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as exc:
        raise CommandError(f"Could not reach MTN: {exc.reason}")


class Command(BaseCommand):
    help = "Create MTN MoMo sandbox API credentials and print the environment variables to set."

    def add_arguments(self, parser):
        parser.add_argument("--subscription-key", required=True, help="Collections product Primary Key")
        parser.add_argument("--host", default="rentmaster-chi.vercel.app", help="Your site's host name (for callbacks)")

    def handle(self, *args, **opts):
        key = opts["subscription_key"].strip()
        api_user = str(uuid.uuid4())
        headers = {"Ocp-Apim-Subscription-Key": key}
        _post(f"{SANDBOX}/v1_0/apiuser", {**headers, "X-Reference-Id": api_user}, {"providerCallbackHost": opts["host"]})
        api_key = _post(f"{SANDBOX}/v1_0/apiuser/{api_user}/apikey", headers).get("apiKey")
        if not api_key:
            raise CommandError("MTN did not return an API key.")
        self.stdout.write(self.style.SUCCESS("MTN sandbox credentials created. Add these to Vercel:\n"))
        for name, value in [
            ("MTN_MOMO_BASE_URL", SANDBOX),
            ("MTN_MOMO_TARGET_ENV", "sandbox"),
            ("MTN_MOMO_CURRENCY", "EUR"),  # the sandbox only accepts EUR
            ("MTN_MOMO_SUBSCRIPTION_KEY", key),
            ("MTN_MOMO_API_USER", api_user),
            ("MTN_MOMO_API_KEY", api_key),
        ]:
            self.stdout.write(f"{name}={value}")
