from django import forms

from apps.accounts.models import Role, User
from apps.core.forms import BootstrapFormMixin

from .models import Building, Property, Unit


class PropertyForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Property
        fields = ["name", "code", "property_type", "location", "latitude", "longitude", "owner", "managers", "photo", "status", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = User.objects.filter(role=Role.OWNER, is_active=True)
        self.fields["managers"].queryset = User.objects.filter(role__in=[Role.MANAGER, Role.CARETAKER], is_active=True)
        self.fields["managers"].required = False


class BuildingForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Building
        fields = ["name", "floors"]


class UnitForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Unit
        fields = ["number", "unit_type", "monthly_rent", "security_deposit", "status", "electricity_meter", "water_meter", "photo", "notes"]
