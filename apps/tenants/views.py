import secrets

from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import PROPERTY_ADMIN_ROLES, Role, User
from apps.accounts.permissions import role_required
from apps.billing.forms import DepositTransactionForm
from apps.billing.models import DepositTransaction
from apps.billing.services import arrears_row, create_invoice_for_lease
from apps.core.audit import log_action
from apps.core.scoping import leases_for, tenants_for
from apps.properties.models import Unit

from .forms import LeaseForm, TenantDocumentForm, TenantForm, TerminateLeaseForm
from .models import Lease

VIEW_ROLES = (Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER, Role.ACCOUNTANT, Role.CARETAKER)
FINANCE = (Role.SUPER_ADMIN, Role.MANAGER, Role.ACCOUNTANT)


@role_required(*VIEW_ROLES)
def tenant_list(request):
    tenants = tenants_for(request.user)
    q = request.GET.get("q", "").strip()
    if q:
        tenants = tenants.filter(Q(full_name__icontains=q) | Q(tenant_id__icontains=q) | Q(phone__icontains=q))
    return render(request, "tenants/tenant_list.html", {"tenants": tenants, "q": q})


@role_required(*VIEW_ROLES)
def tenant_detail(request, pk):
    tenant = get_object_or_404(tenants_for(request.user), pk=pk)
    leases = tenant.leases.select_related("unit__building__property")
    from apps.billing.models import Payment
    return render(request, "tenants/tenant_detail.html", {
        "tenant": tenant,
        "leases": leases,
        "payments": Payment.objects.filter(invoice__lease__tenant=tenant).select_related("invoice")[:20],
        "doc_form": TenantDocumentForm(),
    })


@role_required(*PROPERTY_ADMIN_ROLES)
def tenant_form(request, pk=None):
    tenant = get_object_or_404(tenants_for(request.user), pk=pk) if pk else None
    form = TenantForm(request.POST or None, request.FILES or None, instance=tenant)
    if request.method == "POST" and form.is_valid():
        tenant = form.save(commit=False)
        if not tenant.pk:
            tenant.registered_by = request.user
        tenant.save()
        messages.success(request, f"Tenant {tenant.tenant_id} saved.")
        return redirect("tenants:detail", tenant.pk)
    return render(request, "form.html", {"form": form, "title": f"Edit {tenant}" if tenant else "Register tenant"})


@require_POST
@role_required(*PROPERTY_ADMIN_ROLES)
def tenant_document_upload(request, pk):
    tenant = get_object_or_404(tenants_for(request.user), pk=pk)
    form = TenantDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.tenant = tenant
        doc.save()
        messages.success(request, "Document uploaded.")
    else:
        messages.error(request, "Upload failed: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("tenants:detail", tenant.pk)


@require_POST
@role_required(*PROPERTY_ADMIN_ROLES)
def tenant_create_login(request, pk):
    """Give a tenant a portal account. The temporary password is shown once."""
    tenant = get_object_or_404(tenants_for(request.user), pk=pk)
    if tenant.user_id:
        messages.info(request, "This tenant already has a portal login.")
        return redirect("tenants:detail", tenant.pk)
    first, _, last = tenant.full_name.partition(" ")
    password = secrets.token_urlsafe(9)
    user = User.objects.create_user(
        username=tenant.tenant_id.lower(), password=password, email=tenant.email,
        first_name=first, last_name=last, role=Role.TENANT, phone=tenant.phone,
    )
    tenant.user = user
    tenant.save(update_fields=["user"])
    messages.success(request, f"Portal login created. Username: {user.username}  Temporary password: {password}  "
                              "(share it securely; it will not be shown again)")
    return redirect("tenants:detail", tenant.pk)


# ---------------------------------------------------------------------------
# Leases
# ---------------------------------------------------------------------------

@role_required(*VIEW_ROLES)
def lease_list(request):
    status = request.GET.get("status", "ACTIVE")
    leases = leases_for(request.user).select_related("tenant", "unit__building__property")
    if status:
        leases = leases.filter(status=status)
    return render(request, "tenants/lease_list.html", {"leases": leases, "status": status, "statuses": Lease.Status.choices})


@role_required(*PROPERTY_ADMIN_ROLES)
def lease_form(request, pk=None):
    lease = get_object_or_404(leases_for(request.user), pk=pk) if pk else None
    initial = {}
    if not lease and request.GET.get("unit"):
        unit = Unit.objects.filter(pk=request.GET["unit"]).first()
        if unit:
            initial = {"unit": unit, "monthly_rent": unit.monthly_rent, "security_deposit": unit.security_deposit}
    if not lease and request.GET.get("tenant"):
        initial["tenant"] = request.GET["tenant"]
    form = LeaseForm(request.POST or None, request.FILES or None, instance=lease, initial=initial,
                     user=request.user, tenants=tenants_for(request.user))
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            lease = form.save()
            if lease.status == Lease.Status.ACTIVE:
                Unit.objects.filter(pk=lease.unit_id).update(status=Unit.Status.OCCUPIED)
            if form.cleaned_data.get("record_deposit") and lease.security_deposit:
                DepositTransaction.objects.create(
                    lease=lease, kind=DepositTransaction.Kind.RECEIVED, amount=lease.security_deposit,
                    description="Security deposit at move-in", recorded_by=request.user,
                )
        if not pk and lease.status == Lease.Status.ACTIVE:
            invoice, _ = create_invoice_for_lease(lease, lease.start_date)
            messages.info(request, f"First invoice {invoice.number} generated.")
        messages.success(request, "Lease saved.")
        return redirect("tenants:lease_detail", lease.pk)
    return render(request, "form.html", {"form": form, "title": "Edit lease" if lease else "New lease"})


@role_required(*VIEW_ROLES, Role.TENANT)
def lease_detail(request, pk):
    lease = get_object_or_404(leases_for(request.user).select_related("tenant", "unit__building__property"), pk=pk)
    can_manage_deposit = request.user.role in FINANCE
    return render(request, "tenants/lease_detail.html", {
        "lease": lease,
        "invoices": lease.invoices.all(),
        "arrears": arrears_row(lease),
        "deposit_transactions": lease.deposit_transactions.all(),
        "deposit_held": DepositTransaction.held_for(lease),
        "deposit_form": DepositTransactionForm() if can_manage_deposit else None,
        "terminate_form": TerminateLeaseForm() if request.user.role in PROPERTY_ADMIN_ROLES and lease.status == Lease.Status.ACTIVE else None,
    })


@require_POST
@role_required(*FINANCE)
def lease_deposit_add(request, pk):
    lease = get_object_or_404(leases_for(request.user), pk=pk)
    form = DepositTransactionForm(request.POST)
    if form.is_valid():
        txn = form.save(commit=False)
        held = DepositTransaction.held_for(lease)
        if txn.kind != DepositTransaction.Kind.RECEIVED and txn.amount > held:
            messages.error(request, f"Only {int(held):,} of the deposit is held; cannot deduct/refund {int(txn.amount):,}.")
        else:
            txn.lease = lease
            txn.recorded_by = request.user
            txn.save()
            messages.success(request, f"{txn.get_kind_display()} recorded.")
    else:
        messages.error(request, "Invalid deposit entry.")
    return redirect("tenants:lease_detail", lease.pk)


@require_POST
@role_required(*PROPERTY_ADMIN_ROLES)
def lease_terminate(request, pk):
    lease = get_object_or_404(leases_for(request.user), pk=pk, status=Lease.Status.ACTIVE)
    form = TerminateLeaseForm(request.POST)
    if form.is_valid():
        with transaction.atomic():
            lease.status = Lease.Status.TERMINATED
            lease.end_date = form.cleaned_data["move_out_date"]
            lease.notes = (lease.notes + f"\nTerminated: {form.cleaned_data['reason']}").strip()
            lease.save()
            Unit.objects.filter(pk=lease.unit_id).update(status=Unit.Status.VACANT)
            log_action(f"Terminated lease: {form.cleaned_data['reason']}", lease)
        messages.success(request, f"Lease terminated. Unit {lease.unit.number} is now vacant. "
                                  "Record any deposit deductions/refund below.")
    return redirect("tenants:lease_detail", lease.pk)
