from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.billing.models import Invoice, Payment
from apps.billing.services import add_months
from apps.core.scoping import invoices_for, leases_for, maintenance_for, payments_for, properties_for
from apps.finance.models import Expense
from apps.maintenance.models import MaintenanceRequest
from apps.properties.models import Unit
from apps.tenants.models import Lease

from .models import AuditLog, Notification

OPEN_INVOICE = [Invoice.Status.UNPAID, Invoice.Status.PARTIAL]
OPEN_MAINTENANCE = [MaintenanceRequest.Status.COMPLETED, MaintenanceRequest.Status.CANCELLED]


@login_required
def dashboard(request):
    role = request.user.role
    if role == Role.TENANT:
        return tenant_dashboard(request)
    if role == Role.MAINTENANCE:
        return render(request, "core/dashboard_maintenance.html", {
            "requests": maintenance_for(request.user).exclude(status__in=OPEN_MAINTENANCE).select_related("unit__building__property"),
        })
    return management_dashboard(request)


def _month_bounds(d):
    start = d.replace(day=1)
    return start, add_months(start, 1) - timedelta(days=1)


def management_dashboard(request):
    user = request.user
    today = date.today()
    props = properties_for(user)
    units = Unit.objects.filter(building__property__in=props)
    unit_total = units.count()
    occupied = units.filter(status=Unit.Status.OCCUPIED).count()
    leases = leases_for(user)
    payments = payments_for(user).filter(status=Payment.Status.VERIFIED)
    expenses = Expense.objects.filter(property__in=props)
    invoices = invoices_for(user)

    month_start, month_end = _month_bounds(today)
    collected = payments.filter(verified_at__date__gte=month_start, verified_at__date__lte=month_end).aggregate(s=Sum("amount"))["s"] or 0
    month_expenses = expenses.filter(date__gte=month_start, date__lte=month_end).aggregate(s=Sum("amount"))["s"] or 0
    arrears = invoices.filter(status__in=OPEN_INVOICE, due_date__lt=today).aggregate(
        s=Sum(F("total") - F("amount_paid")))["s"] or 0

    # Six-month trend for the chart.
    trend = []
    for i in range(5, -1, -1):
        s, e = _month_bounds(add_months(month_start, -i))
        trend.append({
            "label": s.strftime("%b %Y"),
            "billed": int(invoices.exclude(status=Invoice.Status.CANCELLED).filter(issue_date__gte=s, issue_date__lte=e).aggregate(v=Sum("total"))["v"] or 0),
            "collected": int(payments.filter(verified_at__date__gte=s, verified_at__date__lte=e).aggregate(v=Sum("amount"))["v"] or 0),
            "expenses": int(expenses.filter(date__gte=s, date__lte=e).aggregate(v=Sum("amount"))["v"] or 0),
        })

    alert_days = settings.RENTMASTER["LEASE_EXPIRY_ALERT_DAYS"]
    return render(request, "core/dashboard.html", {
        "stats": {
            "properties": props.count(), "units": unit_total, "occupied": occupied,
            "tenants": leases.filter(status=Lease.Status.ACTIVE).values("tenant").distinct().count(),
            "occupancy": round(occupied * 100 / unit_total, 1) if unit_total else 0,
            "collected": collected, "arrears": arrears, "expenses": month_expenses, "net": collected - month_expenses,
            "vacant": units.filter(status__in=[Unit.Status.VACANT, Unit.Status.AVAILABLE]).count(),
        },
        "month_label": today.strftime("%B %Y"),
        "trend": trend,
        "expiring": leases.filter(status=Lease.Status.ACTIVE, end_date__lte=today + timedelta(days=alert_days))
                          .select_related("tenant", "unit").order_by("end_date")[:10],
        "recent_payments": payments.select_related("invoice__lease__tenant", "invoice__lease__unit").order_by("-verified_at")[:8],
        "pending_payments": payments_for(user).filter(status=Payment.Status.PENDING).count(),
        "open_maintenance": maintenance_for(user).exclude(status__in=OPEN_MAINTENANCE).select_related("unit").order_by("-created_at")[:8],
    })


def tenant_dashboard(request):
    tenant = getattr(request.user, "tenant_profile", None)
    if tenant is None:
        return render(request, "core/dashboard_tenant.html", {"tenant": None})
    lease = tenant.active_lease
    invoices = invoices_for(request.user)
    open_invoices = invoices.filter(status__in=OPEN_INVOICE).order_by("due_date")
    balance = sum(inv.balance for inv in open_invoices)
    return render(request, "core/dashboard_tenant.html", {
        "tenant": tenant, "lease": lease, "open_invoices": open_invoices, "balance": balance,
        "next_invoice": open_invoices.first(),
        "payments": payments_for(request.user).select_related("receipt", "invoice").order_by("-created_at")[:6],
        "maintenance": maintenance_for(request.user).order_by("-created_at")[:5],
    })


@login_required
def notifications(request):
    notes = request.user.notifications.all()[:100]
    response = render(request, "core/notifications.html", {"notes": notes})
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return response


@login_required
@require_POST
def notification_open(request, pk):
    note = get_object_or_404(Notification, pk=pk, user=request.user)
    note.is_read = True
    note.save(update_fields=["is_read"])
    return redirect(note.link or "notifications")


@role_required(Role.SUPER_ADMIN, Role.ACCOUNTANT)
def audit_log(request):
    logs = AuditLog.objects.select_related("user")
    q = request.GET.get("q", "").strip()
    if q:
        logs = logs.filter(message__icontains=q) | logs.filter(object_repr__icontains=q) | logs.filter(user__username__icontains=q)
    action = request.GET.get("action", "")
    if action:
        logs = logs.filter(action=action)
    return render(request, "core/audit_log.html", {"logs": logs[:300], "q": q, "action": action, "actions": AuditLog.Action.choices})


@role_required(Role.SUPER_ADMIN, Role.MANAGER, Role.CARETAKER)
def announcement(request):
    """Send a notice to every tenant with an active lease (e.g. water shut-off)."""
    from apps.core.notify import notify_tenant

    from .forms import AnnouncementForm

    form = AnnouncementForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        props = properties_for(request.user)
        if form.cleaned_data["property"]:
            props = props.filter(pk=form.cleaned_data["property"].pk)
        leases = Lease.objects.filter(status=Lease.Status.ACTIVE, unit__building__property__in=props).select_related("tenant")
        tenants = {lease.tenant_id: lease.tenant for lease in leases}.values()
        for tenant in tenants:
            notify_tenant(tenant, form.cleaned_data["title"], form.cleaned_data["message"],
                          Notification.Kind.GENERAL, sms=form.cleaned_data["send_sms"])
        from .audit import log_action
        log_action(f"Sent announcement '{form.cleaned_data['title']}' to {len(tenants)} tenants")
        messages.success(request, f"Announcement sent to {len(tenants)} tenant(s).")
        return redirect("dashboard")
    return render(request, "form.html", {"form": form, "title": "Send announcement to tenants", "submit_label": "Send"})


def web_manifest(request):
    """Lets tenants 'Add to home screen' so the portal opens like an app."""
    from django.http import JsonResponse
    from django.templatetags.static import static

    return JsonResponse({
        "name": settings.RENTMASTER["COMPANY_NAME"],
        "short_name": "RENTMASTER",
        "description": "Pay rent, see receipts and report problems.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#0f2440",
        "theme_color": "#0f2440",
        "icons": [{"src": static("core/icon.svg"), "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
    }, content_type="application/manifest+json")


@role_required(Role.SUPER_ADMIN)
def setup_status(request):
    """Go-live checklist for the Super Admin; 'Test payment logins' contacts MTN/Airtel."""
    from .setup_checks import FAIL, run_checks

    live = request.method == "POST"
    results = run_checks(live=live)
    return render(request, "core/setup_status.html", {
        "results": results, "live": live, "fails": sum(1 for r in results if r[0] == FAIL),
    })


def cron_daily(request):
    """Daily billing job for hosts without a task scheduler (Vercel Cron calls this).
    Requires "Authorization: Bearer <CRON_SECRET>"; disabled while CRON_SECRET is unset."""
    import hmac

    from django.http import HttpResponseForbidden, JsonResponse

    from apps.billing.services import run_daily

    secret = settings.CRON_SECRET
    given = request.headers.get("Authorization", "")
    if not secret or not hmac.compare_digest(given, f"Bearer {secret}"):
        return HttpResponseForbidden("Forbidden")
    if settings.DEMO_MODE:
        return JsonResponse({"skipped": "demo mode"})
    result = run_daily()
    from .audit import log_action
    log_action(f"Daily billing job: {result}")
    return JsonResponse(result)
