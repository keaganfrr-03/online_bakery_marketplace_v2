from django import forms
from .models import Profile


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["surname", "phone", "mobile", "delivery_address", "payment_method"]
        labels = {"delivery_address": "Delivery Address"}


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

