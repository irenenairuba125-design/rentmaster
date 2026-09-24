from datetime import date

from django import forms

from apps.core.forms import BootstrapFormMixin, DateInput
from apps.core.scoping import properties_for

from .models import Expense


class ExpenseForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["property", "category", "description", "amount", "date", "payee", "receipt"]
        widgets = {"date": DateInput()}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = properties_for(user)


class ReportFilterForm(BootstrapFormMixin, forms.Form):
    start = forms.DateField(widget=DateInput())
    end = forms.DateField(widget=DateInput())
    property = forms.ModelChoiceField(queryset=None, required=False, empty_label="All properties")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = properties_for(user)
        today = date.today()
        self.fields["start"].initial = today.replace(day=1)
        self.fields["end"].initial = today
