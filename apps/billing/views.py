import csv
import logging
import uuid
from datetime import date

from django.conf import settings
from django.contrib import messages
from django.db.models import Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.models import FINANCE_ROLES, Role
from apps.accounts.permissions import role_required
from apps.core.audit import log_action
from apps.core.scoping import invoices_for, leases_for, payments_for, units_for

from . import services
from .forms import (
    GenerateInvoicesForm, InvoiceItemForm, RejectPaymentForm, StaffPaymentForm, TenantPaymentForm, UtilityReadingForm,
)
from .gateways import GatewayError, GatewayNotConfigured, detect_network
from .models import MOBILE_MONEY_METHODS, Invoice, Payment, PaymentMethod, Receipt, UtilityReading

logger = logging.getLogger("rentmaster.billing")

VIEW_ROLES = (Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER, Role.ACCOUNTANT, Role.CARETAKER, Role.TENANT)
UTILITY_ROLES = (Role.SUPER_ADMIN, Role.MANAGER, Role.ACCOUNTANT, Role.CARETAKER)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@role_required(*VIEW_ROLES)
def invoice_list(request):
    invoices = invoices_for(request.user).select_related("lease__tenant", "lease__unit__building__property")
    status = request.GET.get("status", "")
    if status == "OVERDUE":
        invoices = invoices.filter(status__in=[Invoice.Status.UNPAID, Invoice.Status.PARTIAL], due_date__lt=date.today())
    elif status:
        invoices = invoices.filter(status=status)
    q = request.GET.get("q", "").strip()
    if q:
        invoices = invoices.filter(Q(number__icontains=q) | Q(lease__tenant__full_name__icontains=q) | Q(lease__unit__number__icontains=q))
    totals = invoices.aggregate(total=Sum("total"), paid=Sum("amount_paid"))
    return render(request, "billing/invoice_list.html", {
        "invoices": invoices[:500], "status": status, "q": q, "totals": totals,
        "statuses": Invoice.Status.choices + [("OVERDUE", "Overdue")],
        "generate_form": GenerateInvoicesForm(initial={"billing_date": date.today()}),
    })


@role_required(*VIEW_ROLES)
def invoice_detail(request, pk):
    invoice = get_object_or_404(invoices_for(request.user).select_related("lease__tenant", "lease__unit__building__property"), pk=pk)
    is_finance = request.user.role in FINANCE_ROLES
    open_invoice = invoice.status in (Invoice.Status.UNPAID, Invoice.Status.PARTIAL)
    return render(request, "billing/invoice_detail.html", {
        "invoice": invoice,
        "items": invoice.items.all(),
        "payments": invoice.payments.select_related("receipt", "verified_by"),
        "item_form": InvoiceItemForm() if is_finance and open_invoice else None,
        "payment_form": StaffPaymentForm(invoice=invoice) if is_finance and open_invoice else None,
        "can_pay": request.user.role == Role.TENANT and open_invoice and invoice.balance > 0,
        "can_cancel": is_finance and not invoice.payments.filter(status=Payment.Status.VERIFIED).exists()
                      and invoice.status != Invoice.Status.CANCELLED,
    })


@require_POST
@role_required(*FINANCE_ROLES)
def invoice_generate(request):
    form = GenerateInvoicesForm(request.POST)
    if form.is_valid():
        created = services.generate_invoices(form.cleaned_data["billing_date"])
        log_action(f"Generated {len(created)} invoices for {form.cleaned_data['billing_date']}")
        messages.success(request, f"{len(created)} new invoice(s) generated. Existing invoices were left unchanged.")
    return redirect("billing:invoice_list")


@require_POST
@role_required(*FINANCE_ROLES)
def invoice_item_add(request, pk):
    invoice = get_object_or_404(invoices_for(request.user), pk=pk, status__in=[Invoice.Status.UNPAID, Invoice.Status.PARTIAL])
    form = InvoiceItemForm(request.POST)
    if form.is_valid():
        item = form.save(commit=False)
        item.invoice = invoice
        item.save()
        invoice.recalculate()
        messages.success(request, "Charge added.")
    else:
        messages.error(request, "Invalid charge.")
    return redirect("billing:invoice_detail", invoice.pk)


@require_POST
@role_required(*FINANCE_ROLES)
def invoice_cancel(request, pk):
    invoice = get_object_or_404(invoices_for(request.user), pk=pk)
    if invoice.payments.filter(status=Payment.Status.VERIFIED).exists():
        messages.error(request, "An invoice with verified payments cannot be cancelled.")
    else:
        invoice.status = Invoice.Status.CANCELLED
        invoice.save(update_fields=["status"])
        messages.success(request, f"{invoice.number} cancelled.")
    return redirect("billing:invoice_detail", invoice.pk)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

@require_POST
@role_required(*FINANCE_ROLES)
def payment_record(request, pk):
    """Finance staff record money they have already confirmed (cash, bank statement...)."""
    invoice = get_object_or_404(invoices_for(request.user), pk=pk)
    form = StaffPaymentForm(request.POST, invoice=invoice)
    if form.is_valid():
        payment = Payment.objects.create(
            invoice=invoice, amount=form.cleaned_data["amount"], method=form.cleaned_data["method"],
            payer_reference=form.cleaned_data["payer_reference"], submitted_by=request.user,
        )
        services.confirm_payment(payment, verified_by=request.user)
        messages.success(request, f"Payment of {int(payment.amount):,} recorded and receipt issued.")
    else:
        for errors in form.errors.values():
            for e in errors:
                messages.error(request, e)
    return redirect("billing:invoice_detail", invoice.pk)


def _callback_url(payment):
    """Providers can only call back to a public HTTPS address."""
    base = settings.RENTMASTER["SITE_URL"].rstrip("/")
    if not base.startswith("https://"):
        return None
    return base + reverse("billing:payment_callback", args=[payment.method.lower(), payment.internal_reference])


@role_required(Role.TENANT)
def invoice_pay(request, pk):
    invoice = get_object_or_404(invoices_for(request.user), pk=pk, status__in=[Invoice.Status.UNPAID, Invoice.Status.PARTIAL])
    tenant = invoice.lease.tenant
    initial = {"phone": tenant.phone, "method": detect_network(tenant.phone) or PaymentMethod.MTN_MOMO}
    form = TenantPaymentForm(request.POST or None, invoice=invoice, initial=initial)
    if request.method == "POST" and form.is_valid():
        method, amount = form.cleaned_data["method"], form.cleaned_data["amount"]
        if method in MOBILE_MONEY_METHODS:
            try:
                payment = services.initiate_mobile_money(invoice, amount, method, form.cleaned_data["phone"], request.user,
                                                         callback_url_for=_callback_url)
                messages.success(request, "A payment prompt has been sent to your phone. Enter your PIN to approve, "
                                          "then press 'Check status'.")
            except GatewayNotConfigured:
                messages.warning(request, "Online mobile money collection is not enabled yet. Your payment request was "
                                          "recorded and will be confirmed by the accounts office.")
                payment = invoice.payments.latest("created_at")
            except GatewayError as exc:
                logger.warning("Mobile money initiation failed: %s", exc)
                messages.error(request, "The payment provider could not process the request. Please try again.")
                return redirect("billing:invoice_detail", invoice.pk)
            return redirect("billing:payment_detail", payment.pk)

        payment = Payment.objects.create(
            invoice=invoice, amount=amount, method=PaymentMethod.BANK,
            payer_reference=form.cleaned_data["bank_reference"], submitted_by=request.user,
        )
        messages.success(request, "Thank you. Your bank payment will be marked as paid once the accounts office "
                                  "confirms it on the bank statement.")
        return redirect("billing:payment_detail", payment.pk)
    return render(request, "billing/invoice_pay.html", {"invoice": invoice, "form": form})


@require_POST
@role_required(*VIEW_ROLES)
def payment_status(request, pk):
    """JSON status for the waiting screen. It asks the provider (never trusts the
    browser) and is polled every few seconds while a phone payment is pending."""
    payment = get_object_or_404(payments_for(request.user), pk=pk)
    message = ""
    try:
        payment = services.check_payment_status(payment)
    except GatewayNotConfigured:
        message = "Waiting for the accounts office to confirm."
    except GatewayError as exc:
        logger.info("Status poll failed for payment %s: %s", payment.pk, exc)
        message = "Still waiting for the payment provider."
    payment = Payment.objects.select_related("receipt").get(pk=payment.pk)
    receipt = getattr(payment, "receipt", None) if payment.status == Payment.Status.VERIFIED else None
    return JsonResponse({
        "status": payment.status,
        "status_label": payment.get_status_display(),
        "failure_reason": payment.failure_reason if payment.status == Payment.Status.FAILED else "",
        "receipt_url": reverse("billing:receipt_detail", args=[receipt.pk]) if receipt else None,
        "message": message,
    })


@role_required(*VIEW_ROLES)
def payment_list(request):
    payments = payments_for(request.user).select_related("invoice__lease__tenant", "invoice__lease__unit", "receipt")
    status = request.GET.get("status", "")
    if status:
        payments = payments.filter(status=status)
    method = request.GET.get("method", "")
    if method:
        payments = payments.filter(method=method)
    return render(request, "billing/payment_list.html", {
        "payments": payments[:500], "status": status, "method": method,
        "statuses": Payment.Status.choices, "methods": PaymentMethod.choices,
        "pending_count": payments_for(request.user).filter(status=Payment.Status.PENDING).count(),
    })


@role_required(*VIEW_ROLES)
def payment_detail(request, pk):
    payment = get_object_or_404(payments_for(request.user).select_related("invoice__lease__tenant", "invoice__lease__unit"), pk=pk)
    return render(request, "billing/payment_detail.html", {
        "payment": payment,
        "is_finance": request.user.role in FINANCE_ROLES,
        "reject_form": RejectPaymentForm(),
        "is_mobile": payment.method in MOBILE_MONEY_METHODS,
        "wait_for_phone": payment.status == Payment.Status.PENDING and payment.method in MOBILE_MONEY_METHODS
                          and request.user.role == Role.TENANT,
    })


@require_POST
@role_required(*VIEW_ROLES)
def payment_check(request, pk):
    """Ask the provider for the real status. Never trusts anything the client sends."""
    payment = get_object_or_404(payments_for(request.user), pk=pk)
    try:
        payment = services.check_payment_status(payment)
        if payment.status == Payment.Status.VERIFIED:
            messages.success(request, "Payment confirmed by the provider. Your receipt is ready.")
        elif payment.status == Payment.Status.FAILED:
            messages.error(request, f"The provider reports this payment failed: {payment.failure_reason}")
        else:
            messages.info(request, "The payment is still pending with the provider.")
    except GatewayNotConfigured:
        messages.info(request, "Automatic verification is not enabled for this method; the accounts office will confirm it.")
    except GatewayError as exc:
        logger.warning("Status check failed for payment %s: %s", payment.pk, exc)
        messages.error(request, "Could not reach the payment provider. Try again shortly.")
    return redirect("billing:payment_detail", payment.pk)


@require_POST
@role_required(*FINANCE_ROLES)
def payment_verify(request, pk):
    """Manual confirmation by finance staff (bank transfers, or mobile money checked on the merchant statement)."""
    payment = get_object_or_404(payments_for(request.user), pk=pk, status=Payment.Status.PENDING)
    if request.POST.get("confirmed") != "yes":
        messages.error(request, "Tick the confirmation box after checking the statement.")
        return redirect("billing:payment_detail", payment.pk)
    provider_ref = request.POST.get("provider_reference", "").strip()
    if not provider_ref:
        messages.error(request, "Enter the transaction reference exactly as it appears on the bank/provider statement.")
        return redirect("billing:payment_detail", payment.pk)
    services.confirm_payment(payment, verified_by=request.user, provider_reference=provider_ref)
    messages.success(request, "Payment verified and receipt issued.")
    return redirect("billing:payment_detail", payment.pk)


@require_POST
@role_required(*FINANCE_ROLES)
def payment_reject(request, pk):
    payment = get_object_or_404(payments_for(request.user), pk=pk, status=Payment.Status.PENDING)
    form = RejectPaymentForm(request.POST)
    if form.is_valid():
        services.reject_payment(payment, request.user, form.cleaned_data["reason"])
        messages.success(request, "Payment rejected.")
    return redirect("billing:payment_detail", payment.pk)


@csrf_exempt
@require_POST
def payment_callback(request, provider, reference):
    """Provider webhook. The body is ignored: we only use it as a signal to re-query
    the provider's API for the authoritative status of our own reference."""
    try:
        ref = uuid.UUID(str(reference))
    except ValueError:
        return JsonResponse({"ok": False}, status=400)
    payment = Payment.objects.filter(internal_reference=ref, method=provider.upper(), status=Payment.Status.PENDING).first()
    if payment:
        try:
            services.check_payment_status(payment)
        except GatewayError as exc:
            logger.warning("Callback re-check failed for %s: %s", ref, exc)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

@role_required(*VIEW_ROLES)
def receipt_detail(request, pk):
    receipt = get_object_or_404(Receipt.objects.select_related("payment__invoice__lease__tenant", "payment__invoice__lease__unit__building__property"),
                                pk=pk, payment__in=payments_for(request.user))
    verify_url = settings.RENTMASTER["SITE_URL"].rstrip("/") + reverse("billing:receipt_verify", args=[receipt.verification_code])
    return render(request, "billing/receipt_detail.html", {"receipt": receipt, "payment": receipt.payment, "verify_url": verify_url})


def receipt_verify(request, code):
    """Public page reached by scanning a receipt's QR code. Shows minimal data."""
    receipt = Receipt.objects.select_related("payment__invoice__lease__unit").filter(verification_code=code).first()
    return render(request, "billing/receipt_verify.html", {"receipt": receipt})


# ---------------------------------------------------------------------------
# Arrears & utilities
# ---------------------------------------------------------------------------

@role_required(Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER, Role.ACCOUNTANT, Role.CARETAKER)
def arrears(request):
    from apps.tenants.models import Lease

    only_owing = request.GET.get("all") != "1"
    rows = services.arrears_report(leases_for(request.user).filter(status__in=[Lease.Status.ACTIVE, Lease.Status.EXPIRED, Lease.Status.TERMINATED]),
                                   only_owing=only_owing)
    summary = {}
    for r in rows:
        summary.setdefault(r["classification"], [0, 0])
        summary[r["classification"]][0] += 1
        summary[r["classification"]][1] += r["balance"]
    if request.GET.get("format") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="arrears.csv"'
        w = csv.writer(response)
        w.writerow(["Tenant", "Unit", "Property", "Rent", "Billed", "Paid", "Balance", "Days overdue", "Status"])
        for r in rows:
            w.writerow([r["tenant"].full_name, r["unit"].number, r["unit"].building.property.name, r["rent"], r["billed"],
                        r["paid"], r["balance"], r["days_overdue"], r["classification"]])
        return response
    return render(request, "billing/arrears.html", {"rows": rows, "summary": summary, "only_owing": only_owing,
                                                    "total": sum(r["balance"] for r in rows)})


@role_required(*UTILITY_ROLES)
def utility_list(request):
    readings = UtilityReading.objects.filter(unit__in=units_for(request.user)).select_related("unit__building__property", "invoice_item__invoice")
    form = UtilityReadingForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        reading = form.save(commit=False)
        reading.recorded_by = request.user
        if not reading.meter_number:
            unit = reading.unit
            reading.meter_number = unit.electricity_meter if reading.utility == "ELECTRICITY" else unit.water_meter
        reading.save()
        messages.success(request, f"Reading saved: {reading.consumption:g} units = {int(reading.amount):,}. "
                                  "It will be added to the unit's next invoice.")
        return redirect("billing:utility_list")
    return render(request, "billing/utility_list.html", {"readings": readings[:300], "form": form})


@role_required(*UTILITY_ROLES)
def last_reading(request, unit_pk):
    """Small JSON helper so the reading form can prefill the previous reading."""
    unit = get_object_or_404(units_for(request.user), pk=unit_pk)
    utility = request.GET.get("utility", "ELECTRICITY")
    last = unit.utility_readings.filter(utility=utility).order_by("-reading_date", "-pk").first()
    return JsonResponse({
        "previous_reading": str(last.current_reading) if last else "0",
        "rate": str(last.rate) if last else "",
        "meter_number": unit.electricity_meter if utility == "ELECTRICITY" else unit.water_meter,
    })
