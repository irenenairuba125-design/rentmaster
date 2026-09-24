from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import PROPERTY_ADMIN_ROLES, Role
from apps.accounts.permissions import role_required
from apps.core.scoping import properties_for, units_for

from .forms import BuildingForm, PropertyForm, UnitForm
from .models import Unit

VIEW_ROLES = (Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER, Role.ACCOUNTANT, Role.CARETAKER)


@role_required(*VIEW_ROLES)
def property_list(request):
    props = properties_for(request.user).select_related("owner").annotate(
        unit_count=Count("buildings__units", distinct=True),
        occupied=Count("buildings__units", filter=Q(buildings__units__status=Unit.Status.OCCUPIED), distinct=True),
    )
    return render(request, "properties/property_list.html", {"properties": props})


@role_required(*VIEW_ROLES)
def property_detail(request, pk):
    prop = get_object_or_404(properties_for(request.user), pk=pk)
    buildings = prop.buildings.prefetch_related("units__leases__tenant")
    return render(request, "properties/property_detail.html", {"property": prop, "buildings": buildings})


@role_required(*PROPERTY_ADMIN_ROLES)
def property_form(request, pk=None):
    prop = get_object_or_404(properties_for(request.user), pk=pk) if pk else None
    form = PropertyForm(request.POST or None, request.FILES or None, instance=prop)
    if request.method == "POST" and form.is_valid():
        prop = form.save()
        if request.user.role == Role.MANAGER:
            prop.managers.add(request.user)  # a manager keeps access to what they create
        messages.success(request, f"Property {prop.name} saved.")
        return redirect("properties:detail", prop.pk)
    return render(request, "form.html", {"form": form, "title": f"Edit {prop}" if prop else "New property"})


@role_required(*PROPERTY_ADMIN_ROLES)
def building_form(request, property_pk):
    prop = get_object_or_404(properties_for(request.user), pk=property_pk)
    form = BuildingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        building = form.save(commit=False)
        building.property = prop
        building.save()
        messages.success(request, f"{building.name} added.")
        return redirect("properties:detail", prop.pk)
    return render(request, "form.html", {"form": form, "title": f"Add building to {prop}"})


@role_required(*PROPERTY_ADMIN_ROLES)
def unit_form(request, building_pk=None, pk=None):
    unit = get_object_or_404(units_for(request.user), pk=pk) if pk else None
    if unit:
        building = unit.building
    else:
        from .models import Building
        building = get_object_or_404(Building, pk=building_pk, property__in=properties_for(request.user))
    form = UnitForm(request.POST or None, request.FILES or None, instance=unit)
    if request.method == "POST" and form.is_valid():
        unit = form.save(commit=False)
        unit.building = building
        unit.save()
        messages.success(request, f"Unit {unit.number} saved.")
        return redirect("properties:unit_detail", unit.pk)
    return render(request, "form.html", {"form": form, "title": f"Edit unit {unit.number}" if unit else f"Add unit to {building}"})


@role_required(*VIEW_ROLES)
def unit_detail(request, pk):
    unit = get_object_or_404(units_for(request.user).select_related("building__property"), pk=pk)
    return render(request, "properties/unit_detail.html", {
        "unit": unit,
        "leases": unit.leases.select_related("tenant"),
        "readings": unit.utility_readings.all()[:12],
        "maintenance": unit.maintenance_requests.all()[:10],
    })
