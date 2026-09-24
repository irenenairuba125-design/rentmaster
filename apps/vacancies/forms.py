from datetime import date

from django import forms

from apps.core.forms import BootstrapFormMixin, DateInput
from apps.core.scoping import units_for
from apps.properties.models import Unit

from .models import Application, Listing


class ListingForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Listing
        fields = ["unit", "title", "description", "monthly_rent", "available_from", "is_published"]
        widgets = {"available_from": DateInput()}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = units_for(user).exclude(status=Unit.Status.OCCUPIED).select_related("building__property")


class ApplicationForm(BootstrapFormMixin, forms.ModelForm):
    # Honeypot: hidden from people, filled in by bots.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1"}))
    consent = forms.BooleanField(label="I agree that my details may be used to assess this application")

    class Meta:
        model = Application
        fields = ["full_name", "phone", "email", "national_id", "occupation", "employer", "monthly_income",
                  "household_size", "preferred_move_in", "message"]
        widgets = {"preferred_move_in": DateInput()}
        labels = {"monthly_income": "Monthly income (UGX)", "message": "Anything else we should know?"}

    def clean_preferred_move_in(self):
        d = self.cleaned_data.get("preferred_move_in")
        if d and d < date.today():
            raise forms.ValidationError("Choose a date in the future.")
        return d


class ReviewForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Application
        fields = ["status", "viewing_at", "screening_notes"]
        widgets = {"viewing_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Approval goes through the dedicated button so a tenant record gets created.
        self.fields["status"].choices = [c for c in Application.Status.choices if c[0] != Application.Status.APPROVED]

    def clean(self):
        data = super().clean()
        if data.get("status") == Application.Status.VIEWING and not data.get("viewing_at"):
            self.add_error("viewing_at", "Set the viewing date and time.")
        return data
