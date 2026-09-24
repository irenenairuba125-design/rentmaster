from django import forms

from apps.accounts.models import Role, User
from apps.core.forms import BootstrapFormMixin
from apps.core.scoping import units_for

from .models import MaintenanceComment, MaintenanceRequest


class MaintenanceRequestForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ["unit", "title", "description", "priority", "photo"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        units = units_for(user).select_related("building__property")
        self.fields["unit"].queryset = units
        if user.role == Role.TENANT and units.count() == 1:
            self.fields["unit"].initial = units.first()


class MaintenanceUpdateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ["status", "priority", "assigned_to", "vendor", "cost"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = User.objects.filter(role__in=[Role.MAINTENANCE, Role.CARETAKER], is_active=True)
        if user.role == Role.MAINTENANCE:
            # Technicians only move their own ticket along and record costs.
            for name in ("priority", "assigned_to", "vendor"):
                del self.fields[name]


class MaintenanceCommentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = MaintenanceComment
        fields = ["body", "photo"]
        labels = {"body": "Comment"}
