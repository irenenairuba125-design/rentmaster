from datetime import date

from django.conf import settings
from django.db import models

from apps.core.models import Sequence
from apps.properties.models import DOC_EXTS, IMAGE_EXTS, Unit, private_storage


class Tenant(models.Model):
    tenant_id = models.CharField(max_length=20, unique=True, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="tenant_profile", help_text="Portal login (optional)",
    )
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, help_text="e.g. +256772000000")
    email = models.EmailField(blank=True)
    national_id = models.CharField("National ID / Passport No.", max_length=40, blank=True)
    occupation = models.CharField(max_length=100, blank=True)
    current_address = models.CharField(max_length=200, blank=True)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    photo = models.FileField(upload_to="tenants/", blank=True, storage=private_storage, validators=[IMAGE_EXTS])
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="+", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]

    def save(self, *args, **kwargs):
        if not self.tenant_id:
            self.tenant_id = f"TEN-{Sequence.next('tenant'):06d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} ({self.tenant_id})"

    @property
    def active_lease(self):
        return self.leases.filter(status=Lease.Status.ACTIVE).select_related("unit__building__property").first()


class TenantDocument(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=150)
    visible_to_tenant = models.BooleanField(default=True, help_text="Untick for internal documents (e.g. screening notes)")
    file = models.FileField(upload_to="tenant_docs/", storage=private_storage, validators=[DOC_EXTS])
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Lease(models.Model):
    class Frequency(models.TextChoices):
        MONTHLY = "MONTHLY", "Monthly"
        QUARTERLY = "QUARTERLY", "Quarterly"
        BIANNUAL = "BIANNUAL", "Every 6 months"
        ANNUAL = "ANNUAL", "Annually"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        EXPIRED = "EXPIRED", "Expired"
        TERMINATED = "TERMINATED", "Terminated"

    MONTHS_PER_PERIOD = {"MONTHLY": 1, "QUARTERLY": 3, "BIANNUAL": 6, "ANNUAL": 12}

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="leases")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="leases")
    start_date = models.DateField()
    end_date = models.DateField()
    monthly_rent = models.DecimalField(max_digits=12, decimal_places=0)
    security_deposit = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    payment_frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.MONTHLY)
    due_day = models.PositiveSmallIntegerField(default=1, help_text="Day of month rent is due (1-28)")
    grace_period_days = models.PositiveSmallIntegerField(default=5)
    late_fee = models.DecimalField(max_digits=12, decimal_places=0, default=0, help_text="Flat fee once grace period ends")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    agreement = models.FileField(upload_to="leases/", blank=True, storage=private_storage, validators=[DOC_EXTS])
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"Lease {self.pk}: {self.tenant.full_name} - {self.unit.number}"

    @property
    def days_to_expiry(self):
        return (self.end_date - date.today()).days

    @property
    def period_rent(self):
        return self.monthly_rent * self.MONTHS_PER_PERIOD[self.payment_frequency]
