from django import forms

from apps.core.forms import BootstrapFormMixin, DateInput
from apps.core.scoping import leases_for, units_for

from .models import Inspection, InspectionItem, InspectionPhoto


class InspectionForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Inspection
        fields = ["unit", "lease", "kind", "inspection_date", "notes"]
        widgets = {"inspection_date": DateInput()}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = units_for(user).select_related("building__property")
        self.fields["lease"].queryset = leases_for(user).select_related("tenant", "unit")
        self.fields["lease"].required = False

    def clean(self):
        data = super().clean()
        lease, unit = data.get("lease"), data.get("unit")
        if lease and unit and lease.unit_id != unit.pk:
            self.add_error("lease", "This lease is for a different unit.")
        return data


class InspectionItemForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = InspectionItem
        fields = ["area", "condition", "notes"]


ItemFormSet = forms.inlineformset_factory(
    Inspection, InspectionItem, form=InspectionItemForm, extra=0, can_delete=False,
)


class InspectionPhotoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = InspectionPhoto
        fields = ["photo", "caption"]
