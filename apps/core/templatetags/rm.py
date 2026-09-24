from django import template
from django.conf import settings
from django.utils.html import format_html

register = template.Library()

BADGES = {
    # generic / invoice / payment
    "PAID": "success", "VERIFIED": "success", "ACTIVE": "success", "COMPLETED": "success", "OCCUPIED": "success",
    "PARTIAL": "warning", "PENDING": "warning", "RESERVED": "info", "ASSIGNED": "info", "IN_PROGRESS": "primary",
    "UNPAID": "secondary", "SUBMITTED": "secondary", "DRAFT": "secondary", "AVAILABLE": "info",
    "FAILED": "danger", "CANCELLED": "dark", "TERMINATED": "dark", "EXPIRED": "dark",
    "VACANT": "warning", "MAINTENANCE": "danger",
    # inspections & applications
    "GOOD": "success", "MINOR": "warning", "MAJOR": "danger", "UNDER_REVIEW": "info", "VIEWING": "primary",
    "APPROVED": "success", "REJECTED": "danger", "PUBLISHED": "success",
    # priorities
    "LOW": "secondary", "MEDIUM": "info", "HIGH": "warning", "URGENT": "danger",
    # arrears classes
    "Paid": "success", "Partially paid": "info", "Due": "secondary", "Overdue": "warning", "Serious arrears": "danger",
}


@register.filter
def money(value):
    try:
        return f"{settings.RENTMASTER['CURRENCY']} {int(value or 0):,}"
    except (TypeError, ValueError):
        return value


@register.filter
def num(value):
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return value


@register.simple_tag
def badge(value, label=None):
    return format_html('<span class="badge text-bg-{}">{}</span>', BADGES.get(value, "secondary"), label or value)


@register.filter
def get_item(mapping, key):
    return mapping.get(key)
