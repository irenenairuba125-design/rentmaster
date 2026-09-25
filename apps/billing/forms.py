from django import forms

from apps.core.forms import BootstrapFormMixin, DateInput
from apps.core.scoping import units_for

from .models import MOBILE_MONEY_METHODS, DepositTransaction, InvoiceItem, PaymentMethod, UtilityReading


class InvoiceItemForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = InvoiceItem
        fields = ["category", "description", "amount"]


class GenerateInvoicesForm(BootstrapFormMixin, forms.Form):
    billing_date = forms.DateField(widget=DateInput(), help_text="Invoices are created for the period containing this date.")


class StaffPaymentForm(BootstrapFormMixin, forms.Form):
    """Payment recorded by finance staff after they have confirmed the money arrived."""

    amount = forms.DecimalField(max_digits=12, decimal_places=0, min_value=1)
    method = forms.ChoiceField(choices=PaymentMethod.choices)
    payer_reference = forms.CharField(max_length=100, required=False, label="Reference (bank slip, MoMo ID...)")
    confirmed = forms.BooleanField(
        label="I confirm these funds have been received (cash counted / bank or mobile-money statement checked)",
    )

    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.invoice = invoice
        if invoice is not None:
            self.fields["amount"].initial = invoice.balance

    def clean(self):
        data = super().clean()
        if data.get("method") != PaymentMethod.CASH and not data.get("payer_reference"):
            self.add_error("payer_reference", "A reference is required for non-cash payments.")
        return data


class TenantPaymentForm(BootstrapFormMixin, forms.Form):
    METHODS = [
        (PaymentMethod.MTN_MOMO, "MTN Mobile Money"),
        (PaymentMethod.AIRTEL_MONEY, "Airtel Money"),
        (PaymentMethod.BANK, "Bank transfer (already paid)"),
    ]
    method = forms.ChoiceField(choices=METHODS, widget=forms.RadioSelect)
    amount = forms.DecimalField(max_digits=12, decimal_places=0, min_value=500)
    phone = forms.CharField(max_length=20, required=False, help_text="Mobile money number, e.g. 0772 123456",
                            widget=forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel"}))
    bank_reference = forms.CharField(max_length=100, required=False, help_text="Bank deposit / transfer reference")

    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["method"].widget.attrs = {"class": "form-check-input"}
        self.invoice = invoice
        if invoice is not None:
            self.fields["amount"].initial = invoice.balance

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if self.invoice is not None and amount > self.invoice.balance:
            raise forms.ValidationError(f"The outstanding balance is only {int(self.invoice.balance):,}.")
        return amount

    def clean_phone(self):
        phone = self.cleaned_data.get("phone", "").strip()
        if phone:
            from .gateways import GatewayError, normalise_ug_msisdn

            try:
                normalise_ug_msisdn(phone)
            except GatewayError:
                raise forms.ValidationError("Enter a valid Ugandan number, e.g. 0772 123456.")
        return phone

    def clean(self):
        data = super().clean()
        method = data.get("method")
        if method in MOBILE_MONEY_METHODS and not data.get("phone"):
            self.add_error("phone", "Enter the mobile money number to charge.")
        if method == PaymentMethod.BANK and not data.get("bank_reference"):
            self.add_error("bank_reference", "Enter your bank reference so we can match the payment.")
        return data


class RejectPaymentForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(max_length=200)


class UtilityReadingForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = UtilityReading
        fields = ["unit", "utility", "meter_number", "reading_date", "previous_reading", "current_reading", "rate"]
        widgets = {"reading_date": DateInput()}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = units_for(user).select_related("building__property")

    def clean(self):
        data = super().clean()
        prev, cur = data.get("previous_reading"), data.get("current_reading")
        if prev is not None and cur is not None and cur < prev:
            self.add_error("current_reading", "Current reading cannot be lower than the previous reading.")
        return data


class DepositTransactionForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = DepositTransaction
        fields = ["kind", "amount", "description", "date"]
        widgets = {"date": DateInput()}
