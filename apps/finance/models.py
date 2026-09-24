from datetime import date

from django.conf import settings
from django.db import models

from apps.properties.models import DOC_EXTS, Property, private_storage


class Expense(models.Model):
    class Category(models.TextChoices):
        REPAIRS = "REPAIRS", "Repairs & maintenance"
        PLUMBING = "PLUMBING", "Plumbing"
        ELECTRICITY = "ELECTRICITY", "Electricity"
        WATER = "WATER", "Water"
        SECURITY = "SECURITY", "Security"
        CLEANING = "CLEANING", "Cleaning"
        SALARIES = "SALARIES", "Staff salaries"
        TAXES = "TAXES", "Property taxes"
        INSURANCE = "INSURANCE", "Insurance"
        MATERIALS = "MATERIALS", "Maintenance materials"
        CONTRACTORS = "CONTRACTORS", "Contractor payments"
        OTHER = "OTHER", "Other"

    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="expenses")
    category = models.CharField(max_length=15, choices=Category.choices)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    date = models.DateField(default=date.today)
    payee = models.CharField(max_length=150, blank=True)
    receipt = models.FileField(upload_to="expenses/", blank=True, storage=private_storage, validators=[DOC_EXTS])
    maintenance_request = models.ForeignKey("maintenance.MaintenanceRequest", null=True, blank=True, on_delete=models.SET_NULL)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.get_category_display()} {self.amount} ({self.property})"
