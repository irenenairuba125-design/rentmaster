"""Audit trail: automatic model change logging plus explicit action logging."""
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_delete, post_save, pre_save
from django.forms.models import model_to_dict

from .middleware import get_current_request, get_current_user
from .models import AuditLog

SKIP_FIELDS = {"password", "last_login", "updated_at"}


def _client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or None


def _snapshot(instance):
    data = model_to_dict(instance)
    return {k: str(v) for k, v in data.items() if k not in SKIP_FIELDS and not isinstance(v, list)}


def log_action(message, obj=None, user=None, action=AuditLog.Action.ACTION, changes=None):
    return AuditLog.objects.create(
        user=user or get_current_user(),
        action=action,
        model=obj._meta.verbose_name.title() if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        object_repr=str(obj)[:200] if obj is not None else "",
        message=message[:300],
        changes=changes or {},
        ip_address=_client_ip(get_current_request()),
    )


def _pre_save(sender, instance, **kwargs):
    if instance.pk:
        old = sender.objects.filter(pk=instance.pk).first()
        instance._audit_before = _snapshot(old) if old else None


def _post_save(sender, instance, created, **kwargs):
    name = sender._meta.verbose_name
    if created:
        log_action(f"Created {name}", instance, action=AuditLog.Action.CREATE)
        return
    before = getattr(instance, "_audit_before", None) or {}
    after = _snapshot(instance)
    diff = {k: [before.get(k), v] for k, v in after.items() if before.get(k) != v}
    if diff:
        log_action(f"Updated {name}: {', '.join(diff)}", instance, action=AuditLog.Action.UPDATE, changes=diff)


def _post_delete(sender, instance, **kwargs):
    log_action(f"Deleted {sender._meta.verbose_name}", instance, action=AuditLog.Action.DELETE)


def register(*models):
    for model in models:
        uid = f"audit-{model._meta.label}"
        pre_save.connect(_pre_save, sender=model, dispatch_uid=uid + "-pre")
        post_save.connect(_post_save, sender=model, dispatch_uid=uid + "-post")
        post_delete.connect(_post_delete, sender=model, dispatch_uid=uid + "-del")


def _on_login(sender, request, user, **kwargs):
    AuditLog.objects.create(user=user, action=AuditLog.Action.LOGIN, message="Logged in", ip_address=_client_ip(request))


user_logged_in.connect(_on_login, dispatch_uid="audit-login")
