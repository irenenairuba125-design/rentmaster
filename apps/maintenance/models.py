from django.conf import settings
from django.db import models

from apps.core.models import Sequence
from apps.properties.models import IMAGE_EXTS, Unit


class Vendor(models.Model):
    name = models.CharField(max_length=150)
    trade = models.CharField(max_length=80, help_text="e.g. Plumber, Electrician")
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.trade})"


class MaintenanceRequest(models.Model):
    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        ASSIGNED = "ASSIGNED", "Assigned"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    FLOW = [Status.SUBMITTED, Status.ASSIGNED, Status.IN_PROGRESS, Status.COMPLETED]

    ticket = models.CharField(max_length=20, unique=True, editable=False)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="maintenance_requests")
    title = models.CharField(max_length=150)
    description = models.TextField()
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUBMITTED)
    photo = models.FileField(upload_to="maintenance/", blank=True, validators=[IMAGE_EXTS])
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="reported_requests")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_requests",
        limit_choices_to={"role__in": ["MAINTENANCE", "CARETAKER"]},
    )
    vendor = models.ForeignKey(Vendor, null=True, blank=True, on_delete=models.SET_NULL)
    cost = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.ticket:
            self.ticket = f"MT-{Sequence.next('maintenance'):05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.ticket} {self.title}"


class MaintenanceComment(models.Model):
    request = models.ForeignKey(MaintenanceRequest, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    body = models.TextField()
    photo = models.FileField(upload_to="maintenance/", blank=True, validators=[IMAGE_EXTS])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
