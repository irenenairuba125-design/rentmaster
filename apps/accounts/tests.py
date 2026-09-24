from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from apps.accounts import totp
from apps.accounts.models import ApiToken, User
from apps.billing.gateways import GatewayResult
from apps.billing.models import Invoice, Payment
from apps.billing.tests import DemoDataMixin

PASSWORD = "Rentmaster@2026"


class TokenAuthTests(DemoDataMixin, TestCase):
    def setUp(self):
        cache.clear()

    def login(self, username="ronald", **extra):
        return self.client.post("/api/auth/login/", {"username": username, "password": PASSWORD, **extra},
                                content_type="application/json")

    def auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_login_returns_token_that_works(self):
        resp = self.login(device="Pixel 7")
        self.assertEqual(resp.status_code, 200)
        token = resp.json()["token"]
        me = self.client.get("/api/me/", **self.auth(token)).json()
        self.assertEqual(me["unit"], "A102")
        # only the hash is stored
        self.assertFalse(ApiToken.objects.filter(key_hash=token).exists())

    def test_bad_password_and_lockout(self):
        for _ in range(5):
            resp = self.client.post("/api/auth/login/", {"username": "ronald", "password": "wrong"}, content_type="application/json")
            self.assertEqual(resp.status_code, 401)
        self.assertEqual(self.login().status_code, 429)  # even the right password is refused for now

    def test_two_factor_required(self):
        secret = totp.new_secret()
        User.objects.filter(username="ronald").update(totp_secret=secret, totp_enabled=True)
        resp = self.login()
        self.assertEqual(resp.status_code, 401)
        self.assertTrue(resp.json()["two_factor_required"])
        self.assertEqual(self.login(code="000000").status_code, 401)
        self.assertEqual(self.login(code=totp.current_code(secret)).status_code, 200)

    def test_expired_and_revoked_tokens(self):
        token = self.login().json()["token"]
        self.assertEqual(self.client.post("/api/auth/logout/", **self.auth(token)).status_code, 204)
        self.assertEqual(self.client.get("/api/me/", **self.auth(token)).status_code, 401)
        token = self.login().json()["token"]
        ApiToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get("/api/me/", **self.auth(token)).status_code, 401)

    def test_no_basic_auth(self):
        import base64
        cred = base64.b64encode(f"ronald:{PASSWORD}".encode()).decode()
        # Rejected: a password alone must never authenticate API calls.
        self.assertEqual(self.client.get("/api/me/", HTTP_AUTHORIZATION=f"Basic {cred}").status_code, 401)

    def test_tenant_pays_through_api_and_only_provider_can_confirm(self):
        token = self.login().json()["token"]
        inv = self.ronald_lease.invoices.filter(status="UNPAID").first()
        # overpaying is refused
        resp = self.client.post(f"/api/invoices/{inv.pk}/pay/", {"method": "MTN_MOMO", "amount": int(inv.balance) + 1,
                                "phone": "0772123456"}, content_type="application/json", **self.auth(token))
        self.assertEqual(resp.status_code, 400)
        # no credentials configured -> recorded as pending
        resp = self.client.post(f"/api/invoices/{inv.pk}/pay/", {"method": "MTN_MOMO", "amount": int(inv.balance),
                                "phone": "0772123456"}, content_type="application/json", **self.auth(token))
        self.assertEqual(resp.status_code, 201)
        pid = resp.json()["payment"]["id"]
        self.assertEqual(Payment.objects.get(pk=pid).status, Payment.Status.PENDING)

        gw = mock.Mock()
        gw.check.return_value = GatewayResult("SUCCESSFUL", "MTN-77", inv.balance)
        with mock.patch("apps.billing.services.get_gateway", return_value=gw):
            data = self.client.post(f"/api/payments/{pid}/check/", **self.auth(token)).json()
        self.assertEqual(data["status"], "VERIFIED")
        self.assertTrue(data["receipt"].startswith("REC-"))
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PAID)

    def test_cannot_pay_someone_elses_invoice(self):
        token = self.login().json()["token"]
        other = self.other_lease.invoices.first()
        resp = self.client.post(f"/api/invoices/{other.pk}/pay/", {"method": "MTN_MOMO", "amount": 1000,
                                "phone": "0772123456"}, content_type="application/json", **self.auth(token))
        self.assertEqual(resp.status_code, 404)

    def test_staff_cannot_use_tenant_pay_endpoint(self):
        token = self.login("accountant").json()["token"]
        inv = self.ronald_lease.invoices.filter(status="UNPAID").first()
        resp = self.client.post(f"/api/invoices/{inv.pk}/pay/", {"method": "MTN_MOMO", "amount": 1000,
                                "phone": "0772123456"}, content_type="application/json", **self.auth(token))
        self.assertEqual(resp.status_code, 403)
