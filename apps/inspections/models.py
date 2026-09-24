from datetime import date

from django.conf import settings
from django.db import models

from apps.core.models import Sequence
from apps.properties.models import IMAGE_EXTS, Unit
from apps.tenants.models import Lease

DEFAULT_AREAS = ["Walls", "Floor", "Ceiling", "Doors & locks", "Windows", "Kitchen", "Bathroom", "Plumbing", "Electricity"]


class Inspection(models.Model):
    class Kind(models.TextChoices):
        MOVE_IN = "MOVE_IN", "Move-in"
        MOVE_OUT = "MOVE_OUT", "Move-out"
        ROUTINE = "ROUTINE", "Routine"

    class Overall(models.TextChoices):
        GOOD = "GOOD", "Good"
        MINOR = "MINOR", "Needs minor repair"
        MAJOR = "MAJOR", "Needs major repair"

    number = models.CharField(max_length=20, unique=True, editable=False)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="inspections")
    lease = models.ForeignKey(Lease, null=True, blank=True, on_delete=models.SET_NULL, related_name="inspections")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.ROUTINE)
    inspection_date = models.DateField(default=date.today)
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, editable=False)
    overall = models.CharField(max_length=10, choices=Overall.choices, default=Overall.GOOD, editable=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-inspection_date", "-pk"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = f"INS-{Sequence.next('inspection'):04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} {self.unit.number}"

    def refresh_overall(self):
        conditions = set(self.items.values_list("condition", flat=True))
        if InspectionItem.Condition.DAMAGED in conditions:
            self.overall = self.Overall.MAJOR
        elif InspectionItem.Condition.NEEDS_REPAIR in conditions:
            self.overall = self.Overall.MINOR
        else:
            self.overall = self.Overall.GOOD
        self.save(update_fields=["overall"])


class InspectionItem(models.Model):
    class Condition(models.TextChoices):
        GOOD = "GOOD", "Good"
        NEEDS_REPAIR = "NEEDS_REPAIR", "Needs repair"
        DAMAGED = "DAMAGED", "Damaged"
        NA = "NA", "Not applicable"

    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="items")
    area = models.CharField(max_length=60)
    condition = models.CharField(max_length=15, choices=Condition.choices, default=Condition.GOOD)
    notes = models.CharField(max_length=200, blank=True)
    maintenance_request = models.ForeignKey("maintenance.MaintenanceRequest", null=True, blank=True,
                                            on_delete=models.SET_NULL, editable=False)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.area}: {self.get_condition_display()}"


class InspectionPhoto(models.Model):
    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="photos")
    photo = models.FileField(upload_to="inspections/", validators=[IMAGE_EXTS])
    caption = models.CharField(max_length=150, blank=True)
