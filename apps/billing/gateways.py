"""
Payment provider integrations.

Rule: a payment only becomes VERIFIED when the provider's API itself reports the
transaction as successful for the expected amount (or, for cash/bank, when an
authorised staff member confirms it). References typed in by payers and
callback bodies are never trusted on their own - callbacks only trigger a
fresh status query to the provider.
"""
import base64
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings

from .models import PaymentMethod

logger = logging.getLogger("rentmaster.payments")


class GatewayError(Exception):
    pass


class GatewayNotConfigured(GatewayError):
    pass


@dataclass
class GatewayResult:
    status: str  # "SUCCESSFUL", "PENDING" or "FAILED"
    provider_reference: str = ""
    amount: Decimal | None = None
    reason: str = ""
    raw: dict = field(default_factory=dict)


def _http(method, url, headers=None, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode() or "{}"
            return resp.status, json.loads(text) if text.strip().startswith(("{", "[")) else {"body": text}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise GatewayError(f"{method} {url} -> HTTP {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise GatewayError(f"{method} {url} failed: {exc.reason}") from exc


def normalise_ug_msisdn(phone):
    """Return a Ugandan number as 2567XXXXXXXX."""
    digits = "".join(ch for ch in phone or "" if ch.isdigit())
    if digits.startswith("0"):
        digits = "256" + digits[1:]
    elif len(digits) == 9:
        digits = "256" + digits
    if not (digits.startswith("256") and len(digits) == 12):
        raise GatewayError(f"Invalid Ugandan phone number: {phone}")
    return digits


class MtnMomoGateway:
    """MTN MoMo Collections API (request-to-pay)."""

    def __init__(self):
        self.cfg = settings.PAYMENT_PROVIDERS["MTN_MOMO"]
        if not (self.cfg["SUBSCRIPTION_KEY"] and self.cfg["API_USER"] and self.cfg["API_KEY"]):
            raise GatewayNotConfigured("MTN MoMo credentials are not configured")

    def _token(self):
        basic = base64.b64encode(f"{self.cfg['API_USER']}:{self.cfg['API_KEY']}".encode()).decode()
        _, data = _http("POST", f"{self.cfg['BASE_URL']}/collection/token/", {
            "Authorization": f"Basic {basic}", "Ocp-Apim-Subscription-Key": self.cfg["SUBSCRIPTION_KEY"],
        })
        return data["access_token"]

    def _headers(self, extra=None):
        return {
            "Authorization": f"Bearer {self._token()}",
            "X-Target-Environment": self.cfg["TARGET_ENVIRONMENT"],
            "Ocp-Apim-Subscription-Key": self.cfg["SUBSCRIPTION_KEY"],
            **(extra or {}),
        }

    def initiate(self, payment, callback_url=None):
        extra = {"X-Reference-Id": str(payment.internal_reference)}
        if callback_url:
            extra["X-Callback-Url"] = callback_url
        _http("POST", f"{self.cfg['BASE_URL']}/collection/v1_0/requesttopay", self._headers(extra), {
            "amount": str(int(payment.amount)),
            "currency": self.cfg["CURRENCY"],
            "externalId": payment.invoice.number,
            "payer": {"partyIdType": "MSISDN", "partyId": normalise_ug_msisdn(payment.payer_phone)},
            "payerMessage": f"Rent {payment.invoice.number}",
            "payeeNote": f"RENTMASTER {payment.invoice.number}",
        })

    def check(self, payment):
        _, data = _http("GET", f"{self.cfg['BASE_URL']}/collection/v1_0/requesttopay/{payment.internal_reference}", self._headers())
        status = data.get("status", "PENDING")
        return GatewayResult(
            status={"SUCCESSFUL": "SUCCESSFUL", "FAILED": "FAILED", "REJECTED": "FAILED", "TIMEOUT": "FAILED"}.get(status, "PENDING"),
            provider_reference=str(data.get("financialTransactionId") or ""),
            amount=Decimal(str(data["amount"])) if data.get("amount") else None,
            reason=str(data.get("reason") or ""),
            raw=data,
        )


class AirtelMoneyGateway:
    """Airtel Africa collections API (USSD push)."""

    def __init__(self):
        self.cfg = settings.PAYMENT_PROVIDERS["AIRTEL_MONEY"]
        if not (self.cfg["CLIENT_ID"] and self.cfg["CLIENT_SECRET"]):
            raise GatewayNotConfigured("Airtel Money credentials are not configured")

    def _headers(self):
        _, data = _http("POST", f"{self.cfg['BASE_URL']}/auth/oauth2/token", body={
            "client_id": self.cfg["CLIENT_ID"], "client_secret": self.cfg["CLIENT_SECRET"], "grant_type": "client_credentials",
        })
        return {
            "Authorization": f"Bearer {data['access_token']}",
            "X-Country": self.cfg["COUNTRY"],
            "X-Currency": self.cfg["CURRENCY"],
            "Accept": "*/*",
        }

    def _txn_id(self, payment):
        return payment.internal_reference.hex[:20]

    def initiate(self, payment, callback_url=None):
        # Airtel expects the subscriber number without the country code.
        msisdn = normalise_ug_msisdn(payment.payer_phone)[3:]
        _, data = _http("POST", f"{self.cfg['BASE_URL']}/merchant/v1/payments/", self._headers(), {
            "reference": f"Rent {payment.invoice.number}",
            "subscriber": {"country": self.cfg["COUNTRY"], "currency": self.cfg["CURRENCY"], "msisdn": msisdn},
            "transaction": {"amount": int(payment.amount), "country": self.cfg["COUNTRY"],
                            "currency": self.cfg["CURRENCY"], "id": self._txn_id(payment)},
        })
        status = (data.get("status") or {})
        if status.get("success") is False:
            raise GatewayError(status.get("message") or "Airtel rejected the request")

    def check(self, payment):
        _, data = _http("GET", f"{self.cfg['BASE_URL']}/standard/v1/payments/{self._txn_id(payment)}", self._headers())
        txn = (data.get("data") or {}).get("transaction") or {}
        code = txn.get("status")
        return GatewayResult(
            status={"TS": "SUCCESSFUL", "TF": "FAILED", "TE": "FAILED"}.get(code, "PENDING"),
            provider_reference=str(txn.get("airtel_money_id") or ""),
            # Airtel's enquiry does not echo the amount; we sent it ourselves in initiate().
            amount=None,
            reason=str(txn.get("message") or ""),
            raw=data,
        )


GATEWAYS = {
    PaymentMethod.MTN_MOMO: MtnMomoGateway,
    PaymentMethod.AIRTEL_MONEY: AirtelMoneyGateway,
}


def get_gateway(method):
    """Return a configured gateway, raising GatewayNotConfigured if unavailable."""
    cls = GATEWAYS.get(method)
    if cls is None:
        raise GatewayNotConfigured(f"No online gateway for {method}")
    return cls()
