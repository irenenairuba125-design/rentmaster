from django.conf import settings
from django.db import models, transaction


class Sequence(models.Model):
    """Gap-free counters for human-readable numbers (TEN-000001, INV-2026-00001...)."""

    name = models.CharField(max_length=50, unique=True)
    value = models.PositiveIntegerField(default=0)

    @classmethod
    def next(cls, name):
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(name=name)
            seq.value += 1
            seq.save(update_fields=["value"])
            return seq.value

    def __str__(self):
        return f"{self.name}={self.value}"


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE", "Created"
        UPDATE = "UPDATE", "Updated"
        DELETE = "DELETE", "Deleted"
        ACTION = "ACTION", "Action"
        LOGIN = "LOGIN", "Logged in"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=10, choices=Action.choices)
    model = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    object_repr = models.CharField(max_length=200, blank=True)
    message = models.CharField(max_length=300, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} {self.get_action_display()} {self.object_repr}"


class Notification(models.Model):
    class Kind(models.TextChoices):
        LEASE_EXPIRY = "LEASE_EXPIRY", "Lease expiry"
        RENT_DUE = "RENT_DUE", "Rent due"
        RENT_OVERDUE = "RENT_OVERDUE", "Rent overdue"
        PAYMENT = "PAYMENT", "Payment received"
        MAINTENANCE = "MAINTENANCE", "Maintenance update"
        GENERAL = "GENERAL", "General"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.GENERAL)
    title = models.CharField(max_length=150)
    message = models.TextField()
    link = models.CharField(max_length=200, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
