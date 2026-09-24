from datetime import date

from django.conf import settings
from django.db import models

from apps.core.models import Sequence
from apps.properties.models import Unit


class Listing(models.Model):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="listings")
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    monthly_rent = models.DecimalField(max_digits=12, decimal_places=0)
    available_from = models.DateField(default=date.today)
    is_published = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @classmethod
    def public(cls):
        return cls.objects.filter(is_published=True).exclude(unit__status=Unit.Status.OCCUPIED) \
            .select_related("unit__building__property")


class Application(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        UNDER_REVIEW = "UNDER_REVIEW", "Under review"
        VIEWING = "VIEWING", "Viewing scheduled"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    reference = models.CharField(max_length=20, unique=True, editable=False)
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="applications")
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    national_id = models.CharField("National ID / Passport No.", max_length=40, blank=True)
    occupation = models.CharField(max_length=100, blank=True)
    employer = models.CharField(max_length=150, blank=True)
    monthly_income = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)
    household_size = models.PositiveSmallIntegerField(default=1)
    preferred_move_in = models.DateField(null=True, blank=True)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.SUBMITTED)
    viewing_at = models.DateTimeField(null=True, blank=True)
    screening_notes = models.TextField(blank=True, help_text="Internal: references, ID check, previous landlord...")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", null=True, blank=True, on_delete=models.SET_NULL, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"APP-{Sequence.next('application'):05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} {self.full_name}"

    @property
    def rent_to_income(self):
        if self.monthly_income:
            return round(self.listing.monthly_rent * 100 / self.monthly_income)
        return None
