from django import forms


class BootstrapFormMixin:
    """Adds Bootstrap classes to every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput,)):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class AnnouncementForm(BootstrapFormMixin, forms.Form):
    property = forms.ModelChoiceField(queryset=None, required=False, empty_label="All my properties")
    title = forms.CharField(max_length=150)
    message = forms.CharField(widget=forms.Textarea, max_length=600)
    send_sms = forms.BooleanField(required=False, label="Also send by SMS (charges apply)")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .scoping import properties_for

        self.fields["property"].queryset = properties_for(user)
