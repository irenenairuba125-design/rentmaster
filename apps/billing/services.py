"""Billing business logic: invoicing, payment confirmation, arrears and reminders."""
import calendar
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from apps.core.audit import log_action
from apps.core.models import Notification
from apps.core.notify import notify_property_people, notify_tenant
from apps.tenants.models import Lease

from .gateways import GatewayError, GatewayNotConfigured, get_gateway
from .models import (
    MOBILE_MONEY_METHODS, ChargeCategory, Invoice, InvoiceItem, Payment, Receipt, UtilityReading,
)

logger = logging.getLogger("rentmaster.billing")
CURRENCY = settings.RENTMASTER["CURRENCY"]


def money(value):
    return f"{CURRENCY} {int(value or 0):,}"


def add_months(d, months):
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


# ---------------------------------------------------------------------------
# Invoicing
# ---------------------------------------------------------------------------

def billing_period_for(lease, on_date):
    """The lease billing period that contains `on_date`, anchored on lease start."""
    months = Lease.MONTHS_PER_PERIOD[lease.payment_frequency]
    n = 0
    while add_months(lease.start_date, (n + 1) * months) <= on_date:
        n += 1
    start = add_months(lease.start_date, n * months)
    end = add_months(lease.start_date, (n + 1) * months) - timedelta(days=1)
    return start, end


def due_date_for(lease, period_start):
    day = min(lease.due_day, calendar.monthrange(period_start.year, period_start.month)[1])
    due = period_start.replace(day=day)
    return due if due >= period_start else add_months(due, 1)


@transaction.atomic
def create_invoice_for_lease(lease, on_date=None, include_utilities=True):
    """Create the invoice for the period containing `on_date`. Idempotent: returns
    (invoice, created)."""
    on_date = on_date or date.today()
    period_start, period_end = billing_period_for(lease, on_date)
    existing = lease.invoices.exclude(status=Invoice.Status.CANCELLED).filter(period_start=period_start).first()
    if existing:
        return existing, False

    invoice = Invoice.objects.create(
        lease=lease, period_start=period_start, period_end=period_end,
        issue_date=on_date, due_date=due_date_for(lease, period_start),
    )
    InvoiceItem.objects.create(
        invoice=invoice, category=ChargeCategory.RENT, amount=lease.period_rent,
        description=f"Rent {period_start:%d %b %Y} - {period_end:%d %b %Y}",
    )
    if include_utilities:
        bill_utilities(invoice)
    invoice.recalculate()
    return invoice, True


def bill_utilities(invoice):
    """Attach every unbilled meter reading for the unit to this invoice."""
    readings = UtilityReading.objects.select_for_update().filter(unit=invoice.lease.unit, invoice_item__isnull=True)
    for reading in readings:
        item = InvoiceItem.objects.create(
            invoice=invoice, category=reading.utility, amount=reading.amount,
            description=(f"{reading.get_utility_display()}: {reading.previous_reading:g} -> "
                         f"{reading.current_reading:g} ({reading.consumption:g} units @ {reading.rate:g})"),
        )
        reading.invoice_item = item
        reading.save(update_fields=["invoice_item"])


def generate_invoices(on_date=None):
    on_date = on_date or date.today()
    created = []
    leases = Lease.objects.filter(status=Lease.Status.ACTIVE, start_date__lte=on_date, end_date__gte=on_date)
    for lease in leases.select_related("tenant", "unit"):
        invoice, is_new = create_invoice_for_lease(lease, on_date)
        if is_new:
            created.append(invoice)
            notify_tenant(
                lease.tenant, f"New invoice {invoice.number}",
                f"Your invoice of {money(invoice.total)} for unit {lease.unit.number} is due on {invoice.due_date:%d %B %Y}.",
                Notification.Kind.RENT_DUE, reverse("billing:invoice_detail", args=[invoice.pk]),
            )
    return created


def apply_late_fees(on_date=None):
    on_date = on_date or date.today()
    applied = []
    open_invoices = Invoice.objects.filter(
        status__in=[Invoice.Status.UNPAID, Invoice.Status.PARTIAL], lease__late_fee__gt=0
    ).exclude(items__category=ChargeCategory.LATE_FEE).select_related("lease")
    for invoice in open_invoices:
        if on_date > invoice.grace_deadline:
            with transaction.atomic():
                InvoiceItem.objects.create(
                    invoice=invoice, category=ChargeCategory.LATE_FEE, amount=invoice.lease.late_fee,
                    description=f"Late payment fee (unpaid after {invoice.grace_deadline:%d %b %Y})",
                )
                invoice.recalculate()
            applied.append(invoice)
    return applied


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

@transaction.atomic
def confirm_payment(payment, verified_by=None, provider_reference="", provider_response=None):
    """Mark a payment VERIFIED, update the invoice, issue a receipt and notify.
    Safe to call twice: the second call is a no-op."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == Payment.Status.VERIFIED:
        return payment
    payment.status = Payment.Status.VERIFIED
    payment.verified_by = verified_by
    payment.verified_at = timezone.now()
    if provider_reference:
        payment.provider_reference = provider_reference
    if provider_response is not None:
        payment.provider_response = provider_response
    payment.save()

    invoice = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
    invoice.recalculate()
    receipt = Receipt.objects.create(payment=payment)
    log_action(f"Verified payment {money(payment.amount)} ({payment.get_method_display()}) on {invoice.number}; receipt {receipt.number}",
               payment, user=verified_by)

    lease = invoice.lease
    transaction.on_commit(lambda: _payment_notifications(payment, invoice, receipt, lease))
    return payment


def _payment_notifications(payment, invoice, receipt, lease):
    link = reverse("billing:receipt_detail", args=[receipt.pk])
    notify_tenant(
        lease.tenant, "Payment received",
        f"We have received {money(payment.amount)} for unit {lease.unit.number}. Receipt {receipt.number}. "
        f"Balance on {invoice.number}: {money(invoice.balance)}.",
        Notification.Kind.PAYMENT, link,
    )
    notify_property_people(
        lease.unit.property, "Payment received",
        f"{lease.tenant.full_name} paid {money(payment.amount)} for {lease.unit.number} ({invoice.number}).",
        Notification.Kind.PAYMENT, link,
    )


@transaction.atomic
def reject_payment(payment, user, reason):
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != Payment.Status.PENDING:
        raise ValueError("Only pending payments can be rejected")
    payment.status = Payment.Status.FAILED
    payment.failure_reason = reason[:200]
    payment.verified_by = user
    payment.save()
    log_action(f"Rejected payment on {payment.invoice.number}: {reason}", payment, user=user)
    return payment


def initiate_mobile_money(invoice, amount, method, phone, user, callback_url_for=None):
    """Create a PENDING payment and push a payment prompt to the payer's phone."""
    if method not in MOBILE_MONEY_METHODS:
        raise ValueError("Not a mobile money method")
    payment = Payment.objects.create(
        invoice=invoice, amount=amount, method=method, payer_phone=phone, submitted_by=user,
    )
    try:
        get_gateway(method).initiate(payment, callback_url=callback_url_for(payment) if callback_url_for else None)
    except GatewayNotConfigured as exc:
        payment.failure_reason = f"Awaiting manual verification: {exc}"
        payment.save(update_fields=["failure_reason"])
        raise
    except GatewayError as exc:
        payment.status = Payment.Status.FAILED
        payment.failure_reason = str(exc)[:200]
        payment.save(update_fields=["status", "failure_reason"])
        raise
    return payment


def check_payment_status(payment):
    """Ask the provider for the real status of a pending mobile-money payment."""
    if payment.status != Payment.Status.PENDING or payment.method not in MOBILE_MONEY_METHODS:
        return payment
    result = get_gateway(payment.method).check(payment)
    if result.status == "SUCCESSFUL":
        if result.amount is not None and result.amount != payment.amount:
            logger.warning("Amount mismatch on payment %s: expected %s got %s", payment.pk, payment.amount, result.amount)
            payment.failure_reason = f"Provider amount {result.amount} != expected {payment.amount}; needs review"
            payment.provider_response = result.raw
            payment.save(update_fields=["failure_reason", "provider_response"])
            return payment
        return confirm_payment(payment, provider_reference=result.provider_reference, provider_response=result.raw)
    if result.status == "FAILED":
        payment.status = Payment.Status.FAILED
        payment.failure_reason = (result.reason or "Declined by provider")[:200]
        payment.provider_response = result.raw
        payment.save(update_fields=["status", "failure_reason", "provider_response"])
    return payment


def poll_pending_payments():
    checked = 0
    for payment in Payment.objects.filter(status=Payment.Status.PENDING, method__in=MOBILE_MONEY_METHODS):
        try:
            check_payment_status(payment)
            checked += 1
        except GatewayError as exc:
            logger.info("Could not check payment %s: %s", payment.pk, exc)
    return checked


# ---------------------------------------------------------------------------
# Arrears
# ---------------------------------------------------------------------------

class ArrearsClass:
    PAID = "Paid"
    PARTIAL = "Partially paid"
    DUE = "Due"
    OVERDUE = "Overdue"
    SERIOUS = "Serious arrears"


def arrears_row(lease, today=None):
    today = today or date.today()
    invoices = lease.invoices.exclude(status=Invoice.Status.CANCELLED)
    billed = invoices.aggregate(s=Sum("total"))["s"] or Decimal(0)
    paid = invoices.aggregate(s=Sum("amount_paid"))["s"] or Decimal(0)
    balance = max(billed - paid, Decimal(0))
    oldest_open = invoices.filter(status__in=[Invoice.Status.UNPAID, Invoice.Status.PARTIAL]).order_by("due_date").first()
    days = max((today - oldest_open.due_date).days, 0) if oldest_open else 0

    if balance == 0:
        klass = ArrearsClass.PAID
    elif days > settings.RENTMASTER["SERIOUS_ARREARS_DAYS"]:
        klass = ArrearsClass.SERIOUS
    elif days > lease.grace_period_days:
        klass = ArrearsClass.OVERDUE
    elif paid > 0 and oldest_open and oldest_open.amount_paid > 0:
        klass = ArrearsClass.PARTIAL
    else:
        klass = ArrearsClass.DUE
    return {"lease": lease, "tenant": lease.tenant, "unit": lease.unit, "rent": lease.monthly_rent,
            "billed": billed, "paid": paid, "balance": balance, "days_overdue": days, "classification": klass}


def arrears_report(leases, only_owing=False):
    rows = [arrears_row(lease) for lease in leases.select_related("tenant", "unit__building__property")]
    if only_owing:
        rows = [r for r in rows if r["balance"] > 0]
    return sorted(rows, key=lambda r: (-r["days_overdue"], -r["balance"]))


# ---------------------------------------------------------------------------
# Scheduled reminders
# ---------------------------------------------------------------------------

def run_daily(today=None):
    """The daily billing job: invoices, late fees, pending payment checks, reminders.
    Every step is idempotent."""
    today = today or date.today()
    return {
        "invoices_generated": len(generate_invoices(today)),
        "late_fees_applied": len(apply_late_fees(today)),
        "pending_payments_checked": poll_pending_payments(),
        "reminders": send_reminders(today),
    }


def send_reminders(today=None):
    today = today or date.today()
    sent = {"rent_due": 0, "overdue": 0, "lease_expiry": 0}
    before = settings.RENTMASTER["RENT_REMINDER_DAYS_BEFORE"]
    open_invoices = Invoice.objects.filter(status__in=[Invoice.Status.UNPAID, Invoice.Status.PARTIAL]).select_related("lease__tenant", "lease__unit")
    for inv in open_invoices:
        tenant, unit = inv.lease.tenant, inv.lease.unit
        if inv.due_date == today + timedelta(days=before):
            notify_tenant(tenant, "Rent reminder",
                          f"Your rent of {money(inv.balance)} for unit {unit.number} is due on {inv.due_date:%d %B %Y}.",
                          Notification.Kind.RENT_DUE)
            sent["rent_due"] += 1
        elif inv.due_date < today and (today - inv.due_date).days % 7 == 1:
            # Weekly nudges starting the day after the due date.
            notify_tenant(tenant, "Rent overdue",
                          f"Invoice {inv.number} for unit {unit.number} is overdue. Outstanding: {money(inv.balance)}.",
                          Notification.Kind.RENT_OVERDUE)
            sent["overdue"] += 1

    alert_days = settings.RENTMASTER["LEASE_EXPIRY_ALERT_DAYS"]
    for lease in Lease.objects.filter(status=Lease.Status.ACTIVE, end_date__in=[today + timedelta(days=d) for d in (alert_days, 14, 7)]):
        days = (lease.end_date - today).days
        msg = f"Lease for unit {lease.unit.number} ({lease.tenant.full_name}) expires in {days} days on {lease.end_date:%d %B %Y}."
        notify_tenant(lease.tenant, "Lease expiring", msg, Notification.Kind.LEASE_EXPIRY)
        notify_property_people(lease.unit.property, "Lease expiring", msg, Notification.Kind.LEASE_EXPIRY)
        sent["lease_expiry"] += 1

    # Leases past their end date become EXPIRED.
    Lease.objects.filter(status=Lease.Status.ACTIVE, end_date__lt=today).update(status=Lease.Status.EXPIRED)
    return sent
