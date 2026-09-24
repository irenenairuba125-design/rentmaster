from django.conf import settings

from apps.accounts.models import FINANCE_ROLES, Role

MANAGEMENT = (Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER, Role.ACCOUNTANT, Role.CARETAKER)


def navigation(request):
    ctx = {
        "CURRENCY": settings.RENTMASTER["CURRENCY"],
        "COMPANY_NAME": settings.RENTMASTER["COMPANY_NAME"],
        "DEMO_MODE": settings.DEMO_MODE,
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        role = user.role
        ctx["unread_notifications"] = user.notifications.filter(is_read=False).count()
        ctx["nav"] = {
            "properties": role in MANAGEMENT,
            "tenants": role in MANAGEMENT,
            "billing": role != Role.MAINTENANCE,
            "arrears": role in MANAGEMENT,
            "utilities": role in (Role.SUPER_ADMIN, Role.MANAGER, Role.ACCOUNTANT, Role.CARETAKER),
            "finance": role in (*FINANCE_ROLES, Role.OWNER),
            "audit": role in (Role.SUPER_ADMIN, Role.ACCOUNTANT),
            "admin": role == Role.SUPER_ADMIN and user.is_staff,
            "is_finance": role in FINANCE_ROLES,
            "can_manage": role in (Role.SUPER_ADMIN, Role.MANAGER),
            "is_tenant": role == Role.TENANT,
            "inspections": role in (*MANAGEMENT, Role.TENANT),
            "vacancies": role in (Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER, Role.CARETAKER),
            "announce": role in (Role.SUPER_ADMIN, Role.MANAGER, Role.CARETAKER),
        }
    return ctx
