from django import forms

from apps.core.forms import BootstrapFormMixin, DateInput
from apps.core.scoping import units_for
from apps.properties.models import Unit

from .models import Lease, Tenant, TenantDocument


class TenantForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ["full_name", "phone", "email", "national_id", "occupation", "current_address",
                  "emergency_contact_name", "emergency_contact_phone", "photo"]


class TenantDocumentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = TenantDocument
        fields = ["title", "file", "visible_to_tenant"]


class LeaseForm(BootstrapFormMixin, forms.ModelForm):
    record_deposit = forms.BooleanField(required=False, initial=True, label="Security deposit has been received")

    class Meta:
        model = Lease
        fields = ["tenant", "unit", "start_date", "end_date", "monthly_rent", "security_deposit", "payment_frequency",
                  "due_day", "grace_period_days", "late_fee", "agreement", "notes"]
        widgets = {"start_date": DateInput(), "end_date": DateInput()}

    def __init__(self, *args, user=None, tenants=None, **kwargs):
        super().__init__(*args, **kwargs)
        units = units_for(user)
        if not self.instance.pk:
            units = units.filter(status__in=[Unit.Status.AVAILABLE, Unit.Status.VACANT, Unit.Status.RESERVED])
        self.fields["unit"].queryset = units.select_related("building__property")
        self.fields["tenant"].queryset = tenants
        if self.instance.pk:
            del self.fields["record_deposit"]

    def clean_due_day(self):
        day = self.cleaned_data["due_day"]
        if not 1 <= day <= 28:
            raise forms.ValidationError("Choose a day between 1 and 28.")
        return day

    def clean(self):
        data = super().clean()
        start, end, unit = data.get("start_date"), data.get("end_date"), data.get("unit")
        if start and end and end <= start:
            self.add_error("end_date", "End date must be after the start date.")
        if unit and start and end:
            clash = Lease.objects.filter(unit=unit, status=Lease.Status.ACTIVE, start_date__lte=end, end_date__gte=start)
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error("unit", "This unit already has an active lease in that period.")
        return data


class TerminateLeaseForm(BootstrapFormMixin, forms.Form):
    move_out_date = forms.DateField(widget=DateInput())
    reason = forms.CharField(max_length=200)
