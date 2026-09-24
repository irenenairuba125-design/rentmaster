from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import PROPERTY_ADMIN_ROLES, Role
from apps.accounts.permissions import role_required
from apps.core.audit import log_action
from apps.core.models import Notification
from apps.core.notify import notify_property_people, send_sms
from apps.core.scoping import properties_for
from apps.properties.models import Unit
from apps.tenants.models import Tenant

from .forms import ApplicationForm, ListingForm, ReviewForm
from .models import Application, Listing

VIEW = (Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER, Role.CARETAKER)
OPEN = [Application.Status.SUBMITTED, Application.Status.UNDER_REVIEW, Application.Status.VIEWING]


# ---------------------------------------------------------------------------
# Public pages (no login)
# ---------------------------------------------------------------------------

def public_listings(request):
    return render(request, "vacancies/public_list.html", {"listings": Listing.public()})


def public_listing(request, pk):
    listing = get_object_or_404(Listing.public(), pk=pk)
    form = ApplicationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data.get("website"):  # bot
            return render(request, "vacancies/applied.html", {"application": None, "listing": listing})
        app = form.save(commit=False)
        app.listing = listing
        app.save()
        notify_property_people(listing.unit.property, f"New rental application {app.reference}",
                               f"{app.full_name} applied for unit {listing.unit.number}.", Notification.Kind.GENERAL,
                               reverse("vacancies:application_detail", args=[app.pk]))
        send_sms(app.phone, f"Thank you {app.full_name.split()[0]}, we received your application {app.reference} "
                            f"for unit {listing.unit.number}. We will contact you.")
        return render(request, "vacancies/applied.html", {"application": app, "listing": listing})
    return render(request, "vacancies/public_detail.html", {"listing": listing, "form": form})


# ---------------------------------------------------------------------------
# Staff pages
# ---------------------------------------------------------------------------

def _listings_for(user):
    return Listing.objects.filter(unit__building__property__in=properties_for(user)).select_related("unit__building__property")


def _applications_for(user):
    return Application.objects.filter(listing__in=_listings_for(user)).select_related("listing__unit__building__property")


@role_required(*VIEW)
def listing_list(request):
    listings = _listings_for(request.user).annotate(
        open_apps=Count("applications", filter=Q(applications__status__in=OPEN)))
    vacant = Unit.objects.filter(building__property__in=properties_for(request.user),
                                 status__in=[Unit.Status.VACANT, Unit.Status.AVAILABLE]) \
        .exclude(listings__is_published=True).select_related("building__property")
    return render(request, "vacancies/listing_list.html", {
        "listings": listings, "unlisted_vacant": vacant, "can_manage": request.user.role in PROPERTY_ADMIN_ROLES,
    })


@role_required(*PROPERTY_ADMIN_ROLES)
def listing_form(request, pk=None):
    listing = get_object_or_404(_listings_for(request.user), pk=pk) if pk else None
    initial = {}
    if not listing and request.GET.get("unit"):
        unit = Unit.objects.filter(pk=request.GET["unit"], building__property__in=properties_for(request.user)).first()
        if unit:
            initial = {"unit": unit, "monthly_rent": unit.monthly_rent,
                       "title": f"{unit.get_unit_type_display()} at {unit.building.property.name} ({unit.building.property.location})"}
    form = ListingForm(request.POST or None, instance=listing, initial=initial, user=request.user)
    if request.method == "POST" and form.is_valid():
        listing = form.save(commit=False)
        if not listing.pk:
            listing.created_by = request.user
        listing.save()
        messages.success(request, "Listing saved." + (" It is now visible on the public vacancies page." if listing.is_published else ""))
        return redirect("vacancies:listing_list")
    return render(request, "form.html", {"form": form, "title": "Edit listing" if listing else "Publish a vacancy"})


@role_required(*VIEW)
def application_list(request):
    apps = _applications_for(request.user)
    status = request.GET.get("status", "OPEN")
    if status == "OPEN":
        apps = apps.filter(status__in=OPEN)
    elif status:
        apps = apps.filter(status=status)
    return render(request, "vacancies/application_list.html", {
        "applications": apps, "status": status,
        "statuses": [("OPEN", "Open")] + Application.Status.choices,
    })


@role_required(*VIEW)
def application_detail(request, pk):
    app = get_object_or_404(_applications_for(request.user), pk=pk)
    can_manage = request.user.role in PROPERTY_ADMIN_ROLES and app.status not in (Application.Status.APPROVED,)
    form = ReviewForm(request.POST or None, instance=app) if can_manage else None
    if request.method == "POST" and can_manage and form.is_valid():
        before = Application.objects.get(pk=app.pk)
        app = form.save(commit=False)
        app.reviewed_by = request.user
        app.save()
        if app.status == Application.Status.VIEWING and (before.viewing_at != app.viewing_at or before.status != app.status):
            when = timezone.localtime(app.viewing_at).strftime("%d %b %Y at %H:%M")
            send_sms(app.phone, f"Viewing for unit {app.listing.unit.number} ({app.listing.unit.building.property.name}) "
                                f"is scheduled on {when}. Ref {app.reference}.")
        elif app.status == Application.Status.REJECTED and before.status != app.status:
            send_sms(app.phone, f"Thank you for applying ({app.reference}). Unfortunately your application for unit "
                                f"{app.listing.unit.number} was not successful.")
        messages.success(request, "Application updated.")
        return redirect("vacancies:application_detail", app.pk)
    return render(request, "vacancies/application_detail.html", {"app": app, "form": form, "can_manage": can_manage})


@require_POST
@role_required(*PROPERTY_ADMIN_ROLES)
def application_approve(request, pk):
    """Approve: create the tenant record, reserve the unit, close the listing,
    then continue to the lease form."""
    app = get_object_or_404(_applications_for(request.user), pk=pk, status__in=OPEN)
    unit = app.listing.unit
    if unit.status == Unit.Status.OCCUPIED:
        messages.error(request, "This unit is already occupied.")
        return redirect("vacancies:application_detail", app.pk)
    with transaction.atomic():
        tenant = Tenant.objects.create(
            full_name=app.full_name, phone=app.phone, email=app.email, national_id=app.national_id,
            occupation=app.occupation, registered_by=request.user,
        )
        app.status = Application.Status.APPROVED
        app.tenant = tenant
        app.reviewed_by = request.user
        app.save()
        Unit.objects.filter(pk=unit.pk).update(status=Unit.Status.RESERVED)
        Listing.objects.filter(pk=app.listing_id).update(is_published=False)
        log_action(f"Approved application {app.reference}; created tenant {tenant.tenant_id}", app)
    send_sms(app.phone, f"Congratulations! Your application {app.reference} for unit {unit.number} has been approved. "
                        "We will contact you to sign the tenancy agreement.")
    messages.success(request, f"Approved. Tenant {tenant.tenant_id} created and unit {unit.number} reserved. Now set up the lease.")
    return redirect(reverse("tenants:lease_create") + f"?unit={unit.pk}&tenant={tenant.pk}")
