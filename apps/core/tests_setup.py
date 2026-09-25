import io
import json
import os
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.billing.tests import DemoDataMixin
from rentmaster import startup


class StartupTests(TestCase):
    def test_ensure_admin_creates_once_and_never_overwrites(self):
        env = {"RENTMASTER_ADMIN_USERNAME": "boss", "RENTMASTER_ADMIN_PASSWORD": "Str0ng-pass-123"}
        with mock.patch.dict(os.environ, env):
            user = startup.ensure_admin()
            self.assertTrue(user.is_superuser)
            self.assertEqual(user.role, Role.SUPER_ADMIN)
            user.set_password("changed-later-1")
            user.save()
            self.assertIsNone(startup.ensure_admin())
        self.assertTrue(User.objects.get(username="boss").check_password("changed-later-1"))

    def test_no_admin_without_variables(self):
        with mock.patch.dict(os.environ, {"RENTMASTER_ADMIN_USERNAME": "", "RENTMASTER_ADMIN_PASSWORD": ""}):
            self.assertIsNone(startup.ensure_admin())

    def test_migrations_are_current(self):
        self.assertEqual(startup.pending_migrations(), [])
        self.assertFalse(startup.migrate_if_needed())


class CommandTests(TestCase):
    def test_check_setup_flags_default_secret(self):
        out = io.StringIO()
        call_command("check_setup", stdout=out)
        self.assertIn("Secret key", out.getvalue())
        self.assertIn("must be fixed", out.getvalue())

    def test_generate_secret_key(self):
        out = io.StringIO()
        call_command("generate_secret_key", stdout=out)
        self.assertGreaterEqual(len(out.getvalue().strip()), 50)

    def test_mtn_sandbox_user(self):
        calls = []

        class Resp:
            def __init__(self, body): self.body = body
            def read(self): return self.body
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=None):
            calls.append((req.full_url, dict(req.header_items())))
            return Resp(json.dumps({"apiKey": "k123"}).encode() if req.full_url.endswith("/apikey") else b"")

        out = io.StringIO()
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            call_command("mtn_sandbox_user", "--subscription-key", "SUB", stdout=out)
        self.assertEqual(len(calls), 2)
        self.assertIn("MTN_MOMO_API_KEY=k123", out.getvalue())
        self.assertIn("MTN_MOMO_CURRENCY=EUR", out.getvalue())


class SetupPageAndCronTests(DemoDataMixin, TestCase):
    def test_setup_page_is_super_admin_only(self):
        self.login("owner")
        self.assertEqual(self.client.get(reverse("setup_status")).status_code, 403)
        self.login("admin")
        resp = self.client.get(reverse("setup_status"))
        self.assertContains(resp, "Secret key")
        self.assertContains(self.client.post(reverse("setup_status")), "Tested just now")

    def test_cron_requires_secret(self):
        url = reverse("cron_daily")
        self.assertEqual(self.client.get(url).status_code, 403)  # no secret configured: disabled
        with override_settings(CRON_SECRET="s3cret"):
            self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION="Bearer wrong").status_code, 403)
            resp = self.client.get(url, HTTP_AUTHORIZATION="Bearer s3cret")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("invoices_generated", resp.json())
