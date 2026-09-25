from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.billing.gateways import GatewayNotConfigured, SimulatedGateway, detect_network, get_gateway
from apps.billing.models import Invoice, Payment
from apps.billing.tests import DemoDataMixin


class NetworkDetectionTests(TestCase):
    def test_detect_network(self):
        self.assertEqual(detect_network("0772 123456"), "MTN_MOMO")
        self.assertEqual(detect_network("+256 701 234567"), "AIRTEL_MONEY")
        self.assertEqual(detect_network("256751234567"), "AIRTEL_MONEY")
        self.assertIsNone(detect_network("12345"))

    def test_real_site_never_simulates(self):
        with self.assertRaises(GatewayNotConfigured):
            get_gateway("MTN_MOMO")

    @override_settings(DEMO_MODE=True)
    def test_demo_site_simulates(self):
        self.assertIsInstance(get_gateway("MTN_MOMO"), SimulatedGateway)


class PhonePaymentFlowTests(DemoDataMixin, TestCase):
    def setUp(self):
        self.invoice = self.ronald_lease.invoices.filter(status="UNPAID").first()
        self.login("ronald")

    def test_pay_page_prefills_phone_and_network(self):
        resp = self.client.get(reverse("billing:invoice_pay", args=[self.invoice.pk]))
        self.assertContains(resp, "+256772123456")
        self.assertContains(resp, 'value="MTN_MOMO"')
        self.assertEqual(resp.context["form"].initial["method"], "MTN_MOMO")

    def test_invalid_phone_is_rejected(self):
        resp = self.client.post(reverse("billing:invoice_pay", args=[self.invoice.pk]),
                                {"method": "MTN_MOMO", "amount": int(self.invoice.balance), "phone": "12345"})
        self.assertContains(resp, "valid Ugandan number")
        self.assertFalse(self.invoice.payments.exists())

    @override_settings(DEMO_MODE=True)
    def test_demo_phone_payment_completes_with_receipt(self):
        resp = self.client.post(reverse("billing:invoice_pay", args=[self.invoice.pk]),
                                {"method": "MTN_MOMO", "amount": int(self.invoice.balance), "phone": "0772123456"})
        payment = self.invoice.payments.latest("created_at")
        self.assertRedirects(resp, reverse("billing:payment_detail", args=[payment.pk]))
        page = self.client.get(resp["Location"])
        self.assertContains(page, "Check your phone")

        status_url = reverse("billing:payment_status", args=[payment.pk])
        self.assertEqual(self.client.post(status_url).json()["status"], "PENDING")  # PIN not "entered" yet
        Payment.objects.filter(pk=payment.pk).update(created_at=payment.created_at - timedelta(seconds=30))
        data = self.client.post(status_url).json()
        self.assertEqual(data["status"], "VERIFIED")
        self.assertTrue(data["receipt_url"])
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)

    def test_real_site_status_stays_pending_without_provider(self):
        self.client.post(reverse("billing:invoice_pay", args=[self.invoice.pk]),
                         {"method": "AIRTEL_MONEY", "amount": int(self.invoice.balance), "phone": "0701234567"})
        payment = self.invoice.payments.latest("created_at")
        Payment.objects.filter(pk=payment.pk).update(created_at=payment.created_at - timedelta(minutes=5))
        data = self.client.post(reverse("billing:payment_status", args=[payment.pk])).json()
        self.assertEqual(data["status"], "PENDING")

    def test_status_endpoint_is_scoped(self):
        other = self.other_lease.invoices.first().payments.first()
        self.assertEqual(self.client.post(reverse("billing:payment_status", args=[other.pk])).status_code, 404)

    def test_manifest_for_home_screen(self):
        data = self.client.get(reverse("web_manifest")).json()
        self.assertEqual(data["display"], "standalone")
        self.assertTrue(data["icons"])
