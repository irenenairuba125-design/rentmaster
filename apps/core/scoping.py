"""Row-level access: which records each role may see."""
from apps.accounts.models import Role

ALL_ACCESS = (Role.SUPER_ADMIN, Role.ACCOUNTANT)


def properties_for(user):
    from apps.properties.models import Property

    qs = Property.objects.all()
    if user.role in ALL_ACCESS:
        return qs
    if user.role == Role.OWNER:
        return qs.filter(owner=user)
    if user.role in (Role.MANAGER, Role.CARETAKER):
        return qs.filter(managers=user)
    return qs.none()


def units_for(user):
    from apps.properties.models import Unit

    if user.role == Role.TENANT:
        return Unit.objects.filter(leases__tenant__user=user, leases__status="ACTIVE").distinct()
    return Unit.objects.filter(building__property__in=properties_for(user))


def tenants_for(user):
    from apps.tenants.models import Tenant

    if user.role == Role.TENANT:
        return Tenant.objects.filter(user=user)
    if user.role in ALL_ACCESS:
        return Tenant.objects.all()
    if user.role == Role.MAINTENANCE:
        return Tenant.objects.none()
    # Managers/caretakers/owners see tenants leasing on their properties, plus the
    # tenants they registered themselves (who may not have a lease yet).
    from django.db.models import Q

    return Tenant.objects.filter(
        Q(leases__unit__building__property__in=properties_for(user)) | Q(registered_by=user)
    ).distinct()


def leases_for(user):
    from apps.tenants.models import Lease

    if user.role == Role.TENANT:
        return Lease.objects.filter(tenant__user=user)
    return Lease.objects.filter(unit__building__property__in=properties_for(user))


def invoices_for(user):
    from apps.billing.models import Invoice

    if user.role == Role.TENANT:
        return Invoice.objects.filter(lease__tenant__user=user)
    return Invoice.objects.filter(lease__unit__building__property__in=properties_for(user))


def payments_for(user):
    from apps.billing.models import Payment

    return Payment.objects.filter(invoice__in=invoices_for(user))


def maintenance_for(user):
    from apps.maintenance.models import MaintenanceRequest

    if user.role == Role.TENANT:
        return MaintenanceRequest.objects.filter(unit__in=units_for(user))
    if user.role == Role.MAINTENANCE:
        return MaintenanceRequest.objects.filter(assigned_to=user)
    return MaintenanceRequest.objects.filter(unit__building__property__in=properties_for(user))
