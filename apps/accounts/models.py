from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
    OWNER = "OWNER", "Property Owner / Landlord"
    MANAGER = "MANAGER", "Property Manager"
    ACCOUNTANT = "ACCOUNTANT", "Accountant"
    MAINTENANCE = "MAINTENANCE", "Maintenance Staff"
    CARETAKER = "CARETAKER", "Caretaker"
    TENANT = "TENANT", "Tenant"


class User(AbstractUser):
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.TENANT)
    phone = models.CharField(max_length=20, blank=True)
    totp_secret = models.CharField(max_length=64, blank=True, editable=False)
    totp_enabled = models.BooleanField("Two-factor authentication", default=False, editable=False)

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = Role.SUPER_ADMIN
        super().save(*args, **kwargs)

    def has_role(self, *roles):
        return self.is_authenticated and self.role in roles

    @property
    def is_staff_role(self):
        """Internal staff who manage properties on the landlord's behalf."""
        return self.role in STAFF_ROLES

    def __str__(self):
        return self.get_full_name() or self.username


STAFF_ROLES = (Role.SUPER_ADMIN, Role.MANAGER, Role.ACCOUNTANT, Role.CARETAKER)
FINANCE_ROLES = (Role.SUPER_ADMIN, Role.MANAGER, Role.ACCOUNTANT)
PROPERTY_ADMIN_ROLES = (Role.SUPER_ADMIN, Role.MANAGER)


class ApiToken(models.Model):
    """Bearer token for the mobile app. Only a SHA-256 hash of the key is stored,
    so a leaked database does not leak usable tokens."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_tokens")
    key_hash = models.CharField(max_length=64, unique=True)
    device = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} {self.device or 'token'}"
