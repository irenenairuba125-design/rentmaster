from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.core.scoping import leases_for, units_for
from apps.maintenance.models import MaintenanceRequest

from .forms import InspectionForm, InspectionPhotoForm, ItemFormSet
from .models import DEFAULT_AREAS, Inspection, InspectionItem

VIEW = (Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER, Role.ACCOUNTANT, Role.CARETAKER, Role.TENANT)
INSPECT = (Role.SUPER_ADMIN, Role.MANAGER, Role.CARETAKER)


def _scoped(user):
    qs = Inspection.objects.select_related("unit__building__property", "lease__tenant", "inspector")
    if user.role == Role.TENANT:
        # Tenants see the inspections recorded against their own leases.
        return qs.filter(lease__in=leases_for(user))
    return qs.filter(unit__in=units_for(user))


@role_required(*VIEW)
def inspection_list(request):
    return render(request, "inspections/inspection_list.html", {
        "inspections": _scoped(request.user)[:300], "can_inspect": request.user.role in INSPECT,
    })


@role_required(*INSPECT)
def inspection_create(request):
    initial = {}
    if request.GET.get("lease"):
        lease = leases_for(request.user).filter(pk=request.GET["lease"]).first()
        if lease:
            initial = {"lease": lease, "unit": lease.unit, "kind": request.GET.get("kind", Inspection.Kind.MOVE_OUT)}
    elif request.GET.get("unit"):
        initial = {"unit": request.GET["unit"]}
    form = InspectionForm(request.POST or None, initial=initial, user=request.user)
    if request.method == "POST":
        # No initial data on POST: rows left at their defaults must still count as filled in.
        formset = ItemFormSet(request.POST, prefix="items")
    else:
        formset = ItemFormSet(prefix="items", initial=[{"area": a} for a in DEFAULT_AREAS])
        formset.extra = len(DEFAULT_AREAS)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            inspection = form.save(commit=False)
            inspection.inspector = request.user
            inspection.save()
            formset.instance = inspection
            formset.save()
            inspection.refresh_overall()
        messages.success(request, f"Inspection {inspection.number} saved: {inspection.get_overall_display()}.")
        return redirect("inspections:detail", inspection.pk)
    return render(request, "inspections/inspection_form.html", {"form": form, "formset": formset})


@role_required(*VIEW)
def inspection_detail(request, pk):
    inspection = get_object_or_404(_scoped(request.user), pk=pk)
    can_inspect = request.user.role in INSPECT
    photo_form = InspectionPhotoForm(request.POST or None, request.FILES or None) if can_inspect else None
    if request.method == "POST" and can_inspect and photo_form.is_valid():
        photo = photo_form.save(commit=False)
        photo.inspection = inspection
        photo.save()
        messages.success(request, "Photo added.")
        return redirect("inspections:detail", inspection.pk)
    return render(request, "inspections/inspection_detail.html", {
        "inspection": inspection, "items": inspection.items.select_related("maintenance_request"),
        "photos": inspection.photos.all(), "photo_form": photo_form, "can_inspect": can_inspect,
    })


@require_POST
@role_required(*INSPECT)
def item_to_maintenance(request, pk):
    """Open a maintenance ticket for an item that needs repair."""
    item = get_object_or_404(InspectionItem.objects.select_related("inspection__unit"),
                             pk=pk, inspection__in=_scoped(request.user))
    if item.maintenance_request_id:
        messages.info(request, "A maintenance ticket already exists for this item.")
    else:
        ticket = MaintenanceRequest.objects.create(
            unit=item.inspection.unit, title=f"{item.area}: {item.get_condition_display().lower()}",
            description=f"Raised from inspection {item.inspection.number}. {item.notes}".strip(),
            priority=MaintenanceRequest.Priority.HIGH if item.condition == InspectionItem.Condition.DAMAGED
            else MaintenanceRequest.Priority.MEDIUM,
            reported_by=request.user,
        )
        item.maintenance_request = ticket
        item.save(update_fields=["maintenance_request"])
        messages.success(request, f"Maintenance ticket {ticket.ticket} opened.")
    return redirect("inspections:detail", item.inspection_id)
