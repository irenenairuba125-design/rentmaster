import io
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.billing import services
from apps.billing.gateways import GatewayResult
from apps.billing.models import ChargeCategory, Invoice, Payment, PaymentMethod, Receipt
from apps.core.models import AuditLog
from apps.properties.models import Building, Property, Unit
from apps.tenants.models import Lease, Tenant


class DemoDataMixin:
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=io.StringIO())
        cls.ronald = User.objects.get(username="ronald")
        cls.ronald_lease = Lease.objects.get(tenant__user=cls.ronald)
        cls.other_lease = Lease.objects.get(tenant__full_name="Aisha Nambi")

    def login(self, username):
        self.client.force_login(User.objects.get(username=username))

    def open_invoice(self):
        return self.ronald_lease.invoices.filter(status__in=["UNPAID", "PARTIAL"]).first()


class PaymentVerificationTests(DemoDataMixin, TestCase):
    def test_tenant_bank_reference_does_not_mark_invoice_paid(self):
        inv = self.open_invoice()
        self.login("ronald")
        self.client.post(reverse("billing:invoice_pay", args=[inv.pk]),
                         {"method": "BANK", "amount": int(inv.balance), "bank_reference": "FAKE-123"})
        inv.refresh_from_db()
        payment = inv.payments.latest("created_at")
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(inv.status, Invoice.Status.UNPAID)
        self.assertFalse(Receipt.objects.filter(payment=payment).exists())

    def test_mobile_money_without_credentials_stays_pending(self):
        inv = self.open_invoice()
        self.login("ronald")
        self.client.post(reverse("billing:invoice_pay", args=[inv.pk]),
                         {"method": "MTN_MOMO", "amount": int(inv.balance), "phone": "0772123456"})
        payment = inv.payments.latest("created_at")
        self.assertEqual(payment.status, Payment.Status.PENDING)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.UNPAID)

    def _pending_momo(self):
        inv = self.open_invoice()
        return Payment.objects.create(invoice=inv, amount=inv.balance, method=PaymentMethod.MTN_MOMO, payer_phone="0772123456")

    def test_provider_confirmed_payment_is_verified_with_receipt(self):
        payment = self._pending_momo()
        gw = mock.Mock()
        gw.check.return_value = GatewayResult("SUCCESSFUL", "MTN-999", payment.amount, raw={"status": "SUCCESSFUL"})
        with mock.patch("apps.billing.services.get_gateway", return_value=gw):
            services.check_payment_status(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.VERIFIED)
        self.assertEqual(payment.provider_reference, "MTN-999")
        self.assertTrue(Receipt.objects.filter(payment=payment).exists())
        payment.invoice.refresh_from_db()
        self.assertEqual(payment.invoice.status, Invoice.Status.PAID)

    def test_amount_mismatch_is_not_verified(self):
        payment = self._pending_momo()
        gw = mock.Mock()
        gw.check.return_value = GatewayResult("SUCCESSFUL", "MTN-1", Decimal("1000"))
        with mock.patch("apps.billing.services.get_gateway", return_value=gw):
            services.check_payment_status(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertIn("needs review", payment.failure_reason)

    def test_callback_body_is_not_trusted(self):
        payment = self._pending_momo()
        gw = mock.Mock()
        gw.check.return_value = GatewayResult("PENDING")
        with mock.patch("apps.billing.services.get_gateway", return_value=gw):
            resp = self.client.post(
                reverse("billing:payment_callback", args=["mtn_momo", payment.internal_reference]),
                data='{"status": "SUCCESSFUL", "financialTransactionId": "forged"}', content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        gw.check.assert_called_once()
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)

    def test_confirm_payment_is_idempotent(self):
        payment = self._pending_momo()
        services.confirm_payment(payment)
        services.confirm_payment(payment)
        self.assertEqual(Receipt.objects.filter(payment=payment).count(), 1)

    def test_finance_records_cash_payment(self):
        inv = self.open_invoice()
        self.login("accountant")
        self.client.post(reverse("billing:payment_record", args=[inv.pk]),
                         {"amount": int(inv.balance), "method": "CASH", "confirmed": "on"})
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PAID)
        self.assertTrue(AuditLog.objects.filter(message__startswith="Verified payment", user__username="accountant").exists())

    def test_manual_verify_requires_statement_reference(self):
        payment = self._pending_momo()
        self.login("accountant")
        self.client.post(reverse("billing:payment_verify", args=[payment.pk]), {"confirmed": "yes"})
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.client.post(reverse("billing:payment_verify", args=[payment.pk]), {"confirmed": "yes", "provider_reference": "ST-1"})
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.VERIFIED)

    def test_tenant_cannot_verify_own_payment(self):
        payment = self._pending_momo()
        self.login("ronald")
        resp = self.client.post(reverse("billing:payment_verify", args=[payment.pk]), {"confirmed": "yes", "provider_reference": "x"})
        self.assertEqual(resp.status_code, 403)

    def test_tenant_cannot_overpay(self):
        inv = self.open_invoice()
        self.login("ronald")
        resp = self.client.post(reverse("billing:invoice_pay", args=[inv.pk]),
                                {"method": "BANK", "amount": int(inv.balance) + 1, "bank_reference": "X"})
        self.assertEqual(resp.status_code, 200)  # form re-rendered with an error
        self.assertFalse(inv.payments.filter(status="PENDING").exists())


class AccessControlTests(DemoDataMixin, TestCase):
    def test_tenant_cannot_see_other_tenants_invoice(self):
        other = self.other_lease.invoices.first()
        self.login("ronald")
        self.assertEqual(self.client.get(reverse("billing:invoice_detail", args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("tenants:lease_detail", args=[self.other_lease.pk])).status_code, 404)

    def test_tenant_blocked_from_management_pages(self):
        self.login("ronald")
        for name in ("properties:list", "tenants:list", "billing:arrears", "finance:report", "audit_log"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_owner_only_sees_own_properties(self):
        stranger = User.objects.create_user("owner2", password="x", role=Role.OWNER)
        prop = Property.objects.create(name="Other", code="OTH", location="Jinja", owner=stranger)
        self.login("owner")
        self.assertEqual(self.client.get(reverse("properties:detail", args=[prop.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("properties:list")), "Other")

    def test_api_me_returns_tenant_balance(self):
        self.login("ronald")
        data = self.client.get("/api/me/").json()
        self.assertEqual(data["unit"], "A102")
        self.assertGreater(Decimal(data["balance"]), 0)
        # API list is scoped too
        ids = {i["id"] for i in self.client.get("/api/invoices/").json()["results"]}
        self.assertFalse(ids & set(self.other_lease.invoices.values_list("pk", flat=True)))

    def test_receipt_verification_page_is_public(self):
        receipt = Receipt.objects.first()
        resp = self.client.get(reverse("billing:receipt_verify", args=[receipt.verification_code]))
        self.assertContains(resp, "Genuine receipt")
        self.assertNotContains(resp, receipt.payment.invoice.lease.tenant.full_name)


class SmokeTests(DemoDataMixin, TestCase):
    """Every page renders for every role that is allowed to see it."""

    def test_pages(self):
        inv = self.ronald_lease.invoices.first()
        payment = Payment.objects.filter(invoice=inv).first() or Payment.objects.filter(invoice__lease=self.ronald_lease).first()
        receipt = Receipt.objects.filter(payment__invoice__lease=self.ronald_lease).first()
        unit = self.ronald_lease.unit
        prop = unit.building.property
        mreq = unit.maintenance_requests.first()
        pages = {
            "dashboard": [], "notifications": [], "audit_log": [], "properties:list": [], "properties:create": [],
            "properties:detail": [prop.pk], "properties:edit": [prop.pk], "properties:unit_detail": [unit.pk],
            "properties:building_create": [prop.pk], "properties:unit_create": [unit.building.pk], "properties:unit_edit": [unit.pk],
            "tenants:list": [], "tenants:create": [], "tenants:detail": [self.ronald_lease.tenant.pk], "tenants:edit": [self.ronald_lease.tenant.pk],
            "tenants:lease_list": [], "tenants:lease_create": [], "tenants:lease_detail": [self.ronald_lease.pk],
            "tenants:lease_edit": [self.ronald_lease.pk],
            "billing:invoice_list": [], "billing:invoice_detail": [inv.pk], "billing:payment_list": [],
            "billing:payment_detail": [payment.pk], "billing:receipt_detail": [receipt.pk], "billing:arrears": [],
            "billing:utility_list": [], "maintenance:list": [], "maintenance:create": [], "maintenance:detail": [mreq.pk],
            "finance:expense_list": [], "finance:report": [], "password_change": [],
        }
        for username in ("admin", "owner", "manager", "accountant", "john", "caretaker", "ronald"):
            self.login(username)
            for name, args in pages.items():
                resp = self.client.get(reverse(name, args=args))
                self.assertIn(resp.status_code, (200, 403, 404), f"{username} {name} -> {resp.status_code}")
                if username == "admin":
                    self.assertEqual(resp.status_code, 200, f"admin {name}")
        self.login("ronald")
        open_inv = self.ronald_lease.invoices.filter(status="UNPAID").first()
        self.assertEqual(self.client.get(reverse("billing:invoice_pay", args=[open_inv.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("billing:arrears") + "?format=csv").status_code, 403)
        self.login("accountant")
        self.assertEqual(self.client.get(reverse("billing:arrears") + "?format=csv").status_code, 200)
        self.assertEqual(self.client.get(reverse("finance:report") + "?start=2026-01-01&end=2026-12-31&format=csv").status_code, 200)


class BillingLogicTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("o", password="x", role=Role.OWNER)
        prop = Property.objects.create(name="P", code="P", location="K", owner=owner)
        self.unit = Unit.objects.create(building=Building.objects.create(property=prop, name="A"), number="1", monthly_rent=500_000)
        self.tenant = Tenant.objects.create(full_name="T One", phone="0772000000")
        self.lease = Lease.objects.create(tenant=self.tenant, unit=self.unit, start_date=date(2026, 1, 15),
                                          end_date=date(2026, 12, 31), monthly_rent=500_000, due_day=5,
                                          grace_period_days=5, late_fee=20_000)

    def test_ids_are_sequential(self):
        self.assertRegex(self.tenant.tenant_id, r"^TEN-\d{6}$")
        inv, _ = services.create_invoice_for_lease(self.lease, date(2026, 3, 20))
        self.assertRegex(inv.number, r"^INV-2026-\d{5}$")

    def test_period_and_due_date(self):
        inv, _ = services.create_invoice_for_lease(self.lease, date(2026, 3, 20))
        self.assertEqual((inv.period_start, inv.period_end), (date(2026, 3, 15), date(2026, 4, 14)))
        self.assertEqual(inv.due_date, date(2026, 4, 5))  # day 5 falls before the period start, so next month

    def test_generation_is_idempotent(self):
        a, created_a = services.create_invoice_for_lease(self.lease, date(2026, 3, 20))
        b, created_b = services.create_invoice_for_lease(self.lease, date(2026, 3, 25))
        self.assertTrue(created_a)
        self.assertFalse(created_b)
        self.assertEqual(a.pk, b.pk)

    def test_quarterly_rent(self):
        self.lease.payment_frequency = "QUARTERLY"
        self.lease.save()
        inv, _ = services.create_invoice_for_lease(self.lease, date(2026, 2, 1))
        self.assertEqual(inv.total, 1_500_000)

    def test_utilities_billed_once(self):
        from apps.billing.models import UtilityReading
        UtilityReading.objects.create(unit=self.unit, utility="WATER", previous_reading=10, current_reading=22, rate=2000)
        inv, _ = services.create_invoice_for_lease(self.lease, date(2026, 2, 1))
        self.assertEqual(inv.total, 524_000)
        inv2, _ = services.create_invoice_for_lease(self.lease, date(2026, 3, 1))
        self.assertEqual(inv2.total, 500_000)

    def test_late_fee_applied_once_after_grace(self):
        inv, _ = services.create_invoice_for_lease(self.lease, date(2026, 1, 20))
        self.assertEqual(services.apply_late_fees(inv.grace_deadline), [])
        self.assertEqual(len(services.apply_late_fees(inv.grace_deadline + timedelta(days=1))), 1)
        self.assertEqual(services.apply_late_fees(inv.grace_deadline + timedelta(days=2)), [])
        inv.refresh_from_db()
        self.assertEqual(inv.items.filter(category=ChargeCategory.LATE_FEE).count(), 1)
        self.assertEqual(inv.total, 520_000)

    def test_arrears_classification(self):
        inv, _ = services.create_invoice_for_lease(self.lease, date(2026, 1, 20))
        due = inv.due_date
        self.assertEqual(services.arrears_row(self.lease, due)["classification"], "Due")
        self.assertEqual(services.arrears_row(self.lease, due + timedelta(days=8))["classification"], "Overdue")
        self.assertEqual(services.arrears_row(self.lease, due + timedelta(days=40))["classification"], "Serious arrears")
        p = Payment.objects.create(invoice=inv, amount=200_000, method="CASH")
        services.confirm_payment(p)
        row = services.arrears_row(self.lease, due)
        self.assertEqual((row["classification"], row["balance"]), ("Partially paid", 300_000))
        p2 = Payment.objects.create(invoice=inv, amount=300_000, method="CASH")
        services.confirm_payment(p2)
        self.assertEqual(services.arrears_row(self.lease, due + timedelta(days=40))["classification"], "Paid")

    def test_lease_expiry_reminder_and_auto_expire(self):
        sent = services.send_reminders(self.lease.end_date - timedelta(days=30))
        self.assertEqual(sent["lease_expiry"], 1)
        services.send_reminders(self.lease.end_date + timedelta(days=1))
        self.lease.refresh_from_db()
        self.assertEqual(self.lease.status, Lease.Status.EXPIRED)
