from django import forms
from .models import Profile


class ProfileForm(forms.ModelForm):
    email = forms.EmailField(required=True)  # add email to same form

    class Meta:
        model = Profile
        fields = ["surname", "phone", "mobile", "delivery_address", "payment_method"]
        labels = {"delivery_address": "Delivery Address"}

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["email"].initial = user.email
            self.user = user

    def save(self, commit=True):
        profile = super().save(commit=False)
        if commit:
            profile.save()
            if hasattr(self, "user"):
                self.user.email = self.cleaned_data["email"]
                self.user.save()
        return profile


class VendorProfileForm(forms.ModelForm):
    first_name = forms.CharField(required=False, label="First Name")
    last_name = forms.CharField(required=False, label="Last Name")
    email = forms.EmailField(required=False, label="Email")

    class Meta:
        model = Profile
        fields = ["company_name", "vendor_id", "phone", "mobile", "delivery_address"]
        labels = {"delivery_address": "Address"}

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
        choices=[("R", "Rand"), ("$", "USD"), ("€", "Euro")],
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