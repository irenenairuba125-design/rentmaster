"""Permission-checked downloads for files kept in private storage."""
import os

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render

from apps.accounts.models import FINANCE_ROLES, Role
from apps.accounts.permissions import role_required

from .audit import log_action
from .scoping import leases_for, properties_for, tenants_for

STAFF = (Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER, Role.ACCOUNTANT, Role.CARETAKER)


def _serve(field, obj, request, audit=True):
    if not field:
        raise Http404
    try:
        handle = field.open("rb")
    except FileNotFoundError:
        raise Http404
    if audit:
        log_action(f"Downloaded {os.path.basename(field.name)}", obj)
    return FileResponse(handle, filename=os.path.basename(field.name), as_attachment=request.GET.get("download") == "1")


@role_required(*STAFF, Role.TENANT)
def tenant_document(request, pk):
    from apps.tenants.models import TenantDocument

    docs = TenantDocument.objects.filter(tenant__in=tenants_for(request.user))
    if request.user.role == Role.TENANT:
        docs = docs.filter(visible_to_tenant=True)
    doc = get_object_or_404(docs, pk=pk)
    return _serve(doc.file, doc, request)


@role_required(*STAFF, Role.TENANT)
def tenant_photo(request, pk):
    tenant = get_object_or_404(tenants_for(request.user), pk=pk)
    return _serve(tenant.photo, tenant, request, audit=False)


@role_required(*STAFF, Role.TENANT)
def lease_agreement(request, pk):
    lease = get_object_or_404(leases_for(request.user), pk=pk)
    return _serve(lease.agreement, lease, request)


@role_required(*STAFF)
def property_document(request, pk):
    from apps.properties.models import PropertyDocument

    doc = get_object_or_404(PropertyDocument, pk=pk, property__in=properties_for(request.user))
    return _serve(doc.file, doc, request)


@role_required(*FINANCE_ROLES, Role.OWNER)
def expense_receipt(request, pk):
    from apps.finance.models import Expense

    expense = get_object_or_404(Expense, pk=pk, property__in=properties_for(request.user))
    return _serve(expense.receipt, expense, request)


@role_required(Role.TENANT)
def my_documents(request):
    """Tenant portal: my lease agreements, my documents and my receipts."""
    from apps.billing.models import Receipt

    tenant = getattr(request.user, "tenant_profile", None)
    return render(request, "core/my_documents.html", {
        "tenant": tenant,
        "documents": tenant.documents.filter(visible_to_tenant=True) if tenant else [],
        "leases": leases_for(request.user).select_related("unit"),
        "receipts": Receipt.objects.filter(payment__invoice__lease__tenant=tenant).select_related("payment") if tenant else [],
    })
