import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts import totp
from apps.accounts.models import Role, User
from apps.billing.tests import DemoDataMixin
from apps.core.models import Notification
from apps.inspections.models import Inspection
from apps.maintenance.models import MaintenanceRequest
from apps.properties.models import Building, Property, Unit
from apps.tenants.models import Tenant, TenantDocument
from apps.vacancies.models import Application, Listing

PRIVATE = tempfile.mkdtemp()


class InspectionTests(DemoDataMixin, TestCase):
    def _post(self, unit, conditions):
        data = {"unit": unit.pk, "kind": "ROUTINE", "inspection_date": "2026-09-20", "notes": "",
                "items-TOTAL_FORMS": len(conditions), "items-INITIAL_FORMS": 0}
        for i, (area, cond) in enumerate(conditions):
            data.update({f"items-{i}-area": area, f"items-{i}-condition": cond, f"items-{i}-notes": ""})
        return self.client.post(reverse("inspections:create"), data)

    def test_create_computes_overall_and_keeps_default_rows(self):
        self.login("caretaker")
        unit = Unit.objects.get(number="A101")
        self._post(unit, [("Walls", "GOOD"), ("Floor", "GOOD"), ("Windows", "NEEDS_REPAIR")])
        ins = Inspection.objects.filter(unit=unit).latest("pk")
        self.assertEqual(ins.items.count(), 3)
        self.assertEqual(ins.overall, Inspection.Overall.MINOR)
        self.assertRegex(ins.number, r"^INS-\d{4}$")

    def test_damaged_item_opens_maintenance_ticket_once(self):
        self.login("manager")
        unit = Unit.objects.get(number="A103")
        self._post(unit, [("Bathroom", "DAMAGED")])
        item = Inspection.objects.filter(unit=unit).latest("pk").items.get()
        self.assertEqual(item.inspection.overall, Inspection.Overall.MAJOR)
        url = reverse("inspections:item_to_maintenance", args=[item.pk])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(MaintenanceRequest.objects.filter(title__startswith="Bathroom", unit=unit).count(), 1)

    def test_tenant_sees_only_own_inspections(self):
        mine = Inspection.objects.get(lease=self.ronald_lease)
        other = Inspection.objects.create(unit=self.other_lease.unit, lease=self.other_lease)
        self.login("ronald")
        self.assertEqual(self.client.get(reverse("inspections:detail", args=[mine.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("inspections:detail", args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("inspections:create")).status_code, 403)


class VacancyTests(DemoDataMixin, TestCase):
    def setUp(self):
        self.listing = Listing.objects.get(unit__number="B104")

    def _apply(self, **extra):
        data = {"full_name": "Paul Kasozi", "phone": "0772999888", "household_size": 2, "consent": "on", **extra}
        return self.client.post(reverse("vacancies:public_detail", args=[self.listing.pk]), data)

    def test_public_can_browse_and_apply(self):
        self.assertContains(self.client.get(reverse("vacancies:public_list")), self.listing.title)
        resp = self._apply()
        self.assertContains(resp, "APP-")
        self.assertTrue(Application.objects.filter(full_name="Paul Kasozi").exists())
        # the manager is notified
        self.assertTrue(Notification.objects.filter(user__username="manager", title__startswith="New rental application").exists())

    def test_honeypot_blocks_bots(self):
        self._apply(website="http://spam.example")
        self.assertFalse(Application.objects.filter(full_name="Paul Kasozi").exists())

    def test_occupied_unit_listing_is_hidden(self):
        occupied = Listing.objects.create(unit=Unit.objects.get(number="A102"), title="Occupied", monthly_rent=1)
        self.assertEqual(self.client.get(reverse("vacancies:public_detail", args=[occupied.pk])).status_code, 404)

    def test_approve_creates_tenant_and_reserves_unit(self):
        app = Application.objects.get(full_name="Joan Atim")
        self.login("manager")
        resp = self.client.post(reverse("vacancies:application_approve", args=[app.pk]))
        app.refresh_from_db()
        self.assertEqual(app.status, Application.Status.APPROVED)
        self.assertIsNotNone(app.tenant)
        self.assertEqual(Unit.objects.get(number="B104").status, Unit.Status.RESERVED)
        self.assertFalse(Listing.objects.get(pk=self.listing.pk).is_published)
        self.assertIn(f"tenant={app.tenant.pk}", resp["Location"])
        # the manager can now open a lease for the new tenant on the reserved unit
        self.assertEqual(self.client.get(resp["Location"]).status_code, 200)

    def test_other_managers_cannot_see_applications(self):
        outsider = User.objects.create_user("m2", password="x", role=Role.MANAGER)
        self.client.force_login(outsider)
        app = Application.objects.first()
        self.assertEqual(self.client.get(reverse("vacancies:application_detail", args=[app.pk])).status_code, 404)


class TwoFactorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("acc", password="S3cure-pass!", role=Role.ACCOUNTANT)

    def test_totp_known_vector(self):
        # RFC 6238 test secret "12345678901234567890", T=59 -> 94287082 (8 digits) -> last 6 digits 287082
        import base64
        secret = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(totp.current_code(secret, at=59), "287082")

    def test_enable_and_login_with_code(self):
        self.client.force_login(self.user)
        self.client.get(reverse("two_factor_setup"))
        secret = self.client.session["rm_2fa_setup"]
        self.client.post(reverse("two_factor_setup"), {"code": totp.current_code(secret)})
        self.user.refresh_from_db()
        self.assertTrue(self.user.totp_enabled)
        self.client.logout()

        resp = self.client.post(reverse("login"), {"username": "acc", "password": "S3cure-pass!"})
        self.assertRedirects(resp, reverse("login_2fa"))
        self.assertNotIn("_auth_user_id", self.client.session)  # not logged in yet
        self.client.post(reverse("login_2fa"), {"code": "000000"})
        self.assertNotIn("_auth_user_id", self.client.session)
        resp = self.client.post(reverse("login_2fa"), {"code": totp.current_code(secret)})
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))

    def test_too_many_wrong_codes_restart_login(self):
        self.user.totp_secret, self.user.totp_enabled = totp.new_secret(), True
        self.user.save()
        self.client.post(reverse("login"), {"username": "acc", "password": "S3cure-pass!"})
        for _ in range(5):
            resp = self.client.post(reverse("login_2fa"), {"code": "000000"})
        self.assertRedirects(resp, reverse("login"))
        self.assertRedirects(self.client.get(reverse("login_2fa")), reverse("login"))

    def test_admin_login_goes_through_main_login(self):
        resp = self.client.get("/admin/login/?next=/admin/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(reverse("login")))

    @override_settings(RENTMASTER={**__import__("django.conf").conf.settings.RENTMASTER, "REQUIRE_2FA_ROLES": ["ACCOUNTANT"]})
    def test_required_role_is_forced_to_setup(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("two_factor_setup"))


@override_settings(PRIVATE_MEDIA_ROOT=PRIVATE)
class DocumentAccessTests(DemoDataMixin, TestCase):
    def _doc(self, tenant, visible=True):
        from apps.properties.models import _private
        _private.location = PRIVATE  # storage was created at import time
        return TenantDocument.objects.create(tenant=tenant, title="ID copy", visible_to_tenant=visible,
                                             file=SimpleUploadedFile("id.pdf", b"%PDF-1.4 test"))

    def test_tenant_document_permissions(self):
        mine = self._doc(self.ronald_lease.tenant)
        internal = self._doc(self.ronald_lease.tenant, visible=False)
        theirs = self._doc(self.other_lease.tenant)
        url = lambda d: reverse("tenant_document", args=[d.pk])
        self.assertEqual(self.client.get(url(mine)).status_code, 302)  # anonymous -> login
        self.login("ronald")
        self.assertEqual(self.client.get(url(mine)).status_code, 200)
        self.assertEqual(self.client.get(url(internal)).status_code, 404)
        self.assertEqual(self.client.get(url(theirs)).status_code, 404)
        self.login("manager")
        self.assertEqual(self.client.get(url(internal)).status_code, 200)
        self.login("john")
        self.assertEqual(self.client.get(url(mine)).status_code, 403)

    def test_private_files_have_no_public_url(self):
        doc = self._doc(self.ronald_lease.tenant)
        self.assertFalse(Path(doc.file.path).is_relative_to(Path(__import__("django.conf").conf.settings.MEDIA_ROOT)))


class ScopingAndAnnouncementTests(DemoDataMixin, TestCase):
    def test_manager_does_not_see_other_managers_unleased_tenants(self):
        other = User.objects.create_user("m2", password="x", role=Role.MANAGER)
        t = Tenant.objects.create(full_name="Private Person", phone="0700", registered_by=other)
        self.login("manager")
        self.assertEqual(self.client.get(reverse("tenants:detail", args=[t.pk])).status_code, 404)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("tenants:detail", args=[t.pk])).status_code, 200)

    def test_announcement_reaches_active_tenants(self):
        self.login("manager")
        self.client.post(reverse("announcement"), {"title": "Water shut-off", "message": "No water on Saturday 9am-1pm."})
        self.assertTrue(Notification.objects.filter(user=self.ronald, title="Water shut-off").exists())

    def test_backup_command(self):
        with tempfile.TemporaryDirectory() as d, override_settings(BACKUP_DIR=Path(d)):
            call_command("backup_db", stdout=__import__("io").StringIO())
            self.assertEqual(len(list(Path(d).glob("rentmaster-*.json.gz"))), 1)

    def test_new_pages_render(self):
        pages = [reverse("inspections:list"), reverse("inspections:create"), reverse("vacancies:listing_list"),
                 reverse("vacancies:listing_create"), reverse("vacancies:application_list"),
                 reverse("vacancies:application_detail", args=[Application.objects.first().pk]),
                 reverse("inspections:detail", args=[Inspection.objects.first().pk]),
                 reverse("announcement"), reverse("two_factor_setup")]
        self.login("admin")
        for url in pages:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.login("ronald")
        self.assertEqual(self.client.get(reverse("my_documents")).status_code, 200)
        self.assertEqual(self.client.get(reverse("inspections:list")).status_code, 200)
