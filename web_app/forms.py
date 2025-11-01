from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import Profile


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(required=True, label="First Name")
    last_name = forms.CharField(required=True, label="Last Name")
    email = forms.EmailField(required=True, label="Email")

    class Meta:
        model = Profile
        fields = ["phone", "mobile", "delivery_address", "payment_method"]
        labels = {"delivery_address": "Delivery Address"}

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email
            self.user = user

        # ✅ Add Bootstrap classes to all fields
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"

    def save(self, commit=True):
        profile = super().save(commit=False)
        if hasattr(self, "user"):
            self.user.first_name = self.cleaned_data["first_name"]
            self.user.last_name = self.cleaned_data["last_name"]
            self.user.email = self.cleaned_data["email"]
            if commit:
                self.user.save()
        if commit:
            profile.save()
        return profile


class VendorProfileForm(forms.ModelForm):
    first_name = forms.CharField(required=False, label="First Name")
    last_name = forms.CharField(required=False, label="Last Name")
    email = forms.EmailField(required=False, label="Email")

    class Meta:
        model = Profile
        fields = ["company_name", "vendor_id", "phone", "mobile", "delivery_address"]
        labels = {"delivery_address": "Address"}

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if user:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email
            self.user = user

        # Add Bootstrap classes to all fields
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user
        user.first_name = self.cleaned_data.get("first_name", user.first_name)
        user.last_name = self.cleaned_data.get("last_name", user.last_name)
        user.email = self.cleaned_data.get("email", user.email)
        if commit:
            user.save()
            profile.save()
        return profile


class VendorSettingsForm(forms.Form):
    default_currency = forms.ChoiceField(
        choices=[("R", "Rand"), ("$", "ZimDollar"), ("K", "Kwacha")],
        initial="R",
        label="Default Currency"
    )
    low_stock_threshold = forms.IntegerField(
        initial=5, label="Low Stock Alert (Qty)"
    )
    notify_new_order = forms.BooleanField(
        required=False, initial=True, label="Email me for new orders"
    )
    notify_low_stock = forms.BooleanField(
        required=False, initial=True, label="Email me for low stock alerts"
    )
    default_report_period = forms.ChoiceField(
        choices=[("day", "Daily"), ("week", "Weekly"), ("month", "Monthly"), ("all", "All Time")],
        initial="week",
        label="Default Report Period"
    )


class VendorLoginForm(AuthenticationForm):
    vendor_id = forms.CharField(
        required=False,  # for now it's just visual, not validated
        label="For vendors, enter your Vendor ID",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter Vendor ID"}
        ),
    )