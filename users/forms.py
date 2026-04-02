from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import Feedback


class UserRegisterForm(UserCreationForm):
    email = forms.EmailField(widget=forms.EmailInput())

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_classes = "mt-1 w-full rounded-xl border-gray-300 focus:border-indigo-500 focus:ring-indigo-500 p-3"
        placeholders = {
            "username": "Enter username",
            "email": "you@example.com",
            "password1": "Create password",
            "password2": "Confirm password",
        }
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", base_classes)
            if name in placeholders:
                field.widget.attrs.setdefault("placeholder", placeholders[name])


class FeedbackForm(forms.ModelForm):
    class Meta:
        model = Feedback
        fields = ["subject", "message"]
        widgets = {
            "subject": forms.TextInput(attrs={"class": "mt-1 w-full rounded-xl border-gray-300 focus:border-indigo-500 focus:ring-indigo-500 p-3"}),
            "message": forms.Textarea(attrs={"class": "mt-1 w-full rounded-xl border-gray-300 focus:border-indigo-500 focus:ring-indigo-500 p-3", "rows": 5}),
        }
