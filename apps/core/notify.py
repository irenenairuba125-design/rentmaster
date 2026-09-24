"""Outbound communication: in-app notifications, email and SMS."""
import json
import logging
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.mail import send_mail

from .models import Notification

logger = logging.getLogger("rentmaster.notify")


def send_sms(phone, message):
    cfg = settings.SMS
    if not phone:
        return False
    if not (cfg["USERNAME"] and cfg["API_KEY"]):
        logger.info("SMS (not configured, logged only) to %s: %s", phone, message)
        return False
    host = "api.sandbox.africastalking.com" if cfg["USERNAME"] == "sandbox" else "api.africastalking.com"
    payload = {"username": cfg["USERNAME"], "to": phone, "message": message}
    if cfg["SENDER_ID"]:
        payload["from"] = cfg["SENDER_ID"]
    req = urllib.request.Request(
        f"https://{host}/version1/messaging",
        data=urllib.parse.urlencode(payload).encode(),
        headers={"apiKey": cfg["API_KEY"], "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info("SMS sent to %s: %s", phone, json.loads(resp.read() or b"{}"))
            return True
    except Exception:  # a failed SMS must never break a payment or request
        logger.exception("SMS to %s failed", phone)
        return False


def notify_user(user, title, message, kind=Notification.Kind.GENERAL, link="", email=True, sms=False):
    if user is None:
        return None
    note = Notification.objects.create(user=user, kind=kind, title=title, message=message, link=link)
    if email and user.email:
        send_mail(title, message, None, [user.email], fail_silently=True)
    if sms and user.phone:
        send_sms(user.phone, f"{title}: {message}")
    return note


def notify_tenant(tenant, title, message, kind=Notification.Kind.GENERAL, link="", sms=True):
    """Tenants may not have a portal login yet; fall back to their contact details."""
    if tenant.user_id:
        notify_user(tenant.user, title, message, kind, link, email=True, sms=False)
    elif tenant.email:
        send_mail(title, message, None, [tenant.email], fail_silently=True)
    if sms:
        send_sms(tenant.phone, f"{title}: {message}")


def notify_property_people(prop, title, message, kind=Notification.Kind.GENERAL, link=""):
    """Owner and assigned managers of a property."""
    recipients = {prop.owner} if prop.owner_id else set()
    recipients.update(prop.managers.all())
    for user in recipients:
        notify_user(user, title, message, kind, link, email=False)
