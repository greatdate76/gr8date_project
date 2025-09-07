# pages/forms.py
from django import forms

class ContactForm(forms.Form):
    name = forms.CharField(max_length=120, widget=forms.TextInput(attrs={
        "placeholder": "Your name"
    }))
    email = forms.EmailField(widget=forms.EmailInput(attrs={
        "placeholder": "you@example.com"
    }))
    message = forms.CharField(widget=forms.Textarea(attrs={
        "rows": 6,
        "placeholder": "How can we help?"
    }))
    # Honeypot (hidden) to reduce spam bots
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"style": "display:none;"}))

    def clean(self):
        data = super().clean()
        if data.get("website"):  # bot filled hidden field
            raise forms.ValidationError("Spam detected.")
        return data

