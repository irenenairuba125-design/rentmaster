from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.validators import FileExtensionValidator
from django.db import models

IMAGE_EXTS = FileExtensionValidator(["jpg", "jpeg", "png", "webp"])
DOC_EXTS = FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "doc", "docx"])

# Sensitive documents (IDs, agreements, receipts) live outside MEDIA_ROOT and are only
# served through views in apps.core.documents that check the viewer's permissions.
_private = FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)


def private_storage():
    return _private


class Property(models.Model):
    class Type(models.TextChoices):
        APARTMENT = "APARTMENT", "Apartment block"
        HOUSE = "HOUSE", "Houses / estate"
        COMMERCIAL = "COMMERCIAL", "Commercial"
        MIXED = "MIXED", "Mixed use"
        HOSTEL = "HOSTEL", "Hostel"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION", "Under construction"

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, unique=True, help_text="Short code, e.g. ROYAL")
    property_type = models.CharField(max_length=20, choices=Type.choices, default=Type.APARTMENT)
    location = models.CharField(max_length=200)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_properties",
        limit_choices_to={"role": "OWNER"},
    )
    managers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="managed_properties",
        limit_choices_to={"role__in": ["MANAGER", "CARETAKER"]},
        help_text="Managers and caretakers who can work on this property.",
    )
    photo = models.FileField(upload_to="properties/", blank=True, validators=[IMAGE_EXTS])
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "properties"

    def __str__(self):
        return self.name

    @property
    def units(self):
        return Unit.objects.filter(building__property=self)

    def occupancy_rate(self):
        total = self.units.count()
        if not total:
            return 0
        return round(self.units.filter(status=Unit.Status.OCCUPIED).count() * 100 / total, 1)


class PropertyDocument(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=150)
    file = models.FileField(upload_to="property_docs/", storage=private_storage, validators=[DOC_EXTS])
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Building(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="buildings")
    name = models.CharField(max_length=100, help_text="e.g. Block A")
    floors = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["property", "name"]
        unique_together = [("property", "name")]

    def __str__(self):
        return f"{self.property.name} / {self.name}"


class Unit(models.Model):
    class Type(models.TextChoices):
        SINGLE = "SINGLE", "Single room"
        DOUBLE = "DOUBLE", "Double room"
        STUDIO = "STUDIO", "Studio"
        ONE_BED = "1BR", "1 bedroom"
        TWO_BED = "2BR", "2 bedroom"
        THREE_BED = "3BR", "3 bedroom"
        SHOP = "SHOP", "Shop"
        OFFICE = "OFFICE", "Office"

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        RESERVED = "RESERVED", "Reserved"
        OCCUPIED = "OCCUPIED", "Occupied"
        MAINTENANCE = "MAINTENANCE", "Under maintenance"
        VACANT = "VACANT", "Vacant"

    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name="units")
    number = models.CharField(max_length=20)
    unit_type = models.CharField(max_length=10, choices=Type.choices, default=Type.ONE_BED)
    monthly_rent = models.DecimalField(max_digits=12, decimal_places=0)
    security_deposit = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.AVAILABLE)
    electricity_meter = models.CharField(max_length=40, blank=True)
    water_meter = models.CharField(max_length=40, blank=True)
    photo = models.FileField(upload_to="units/", blank=True, validators=[IMAGE_EXTS])
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["building", "number"]
        unique_together = [("building", "number")]

    def __str__(self):
        return f"{self.number} ({self.building.property.name})"

    @property
    def active_lease(self):
        return self.leases.filter(status="ACTIVE").select_related("tenant").first()

    # Defined last: naming an attribute "property" shadows the builtin inside the class body.
    property = property(lambda self: self.building.property)
