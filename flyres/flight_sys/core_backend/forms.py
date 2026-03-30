from django import forms
from typing import Any
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
import re
from django.core.exceptions import ValidationError

from .models import CustomUser


class CreateUserForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = [
            'username',
            'email',
            'password1',
            'password2'
        ]
    def __init__(self, *args: Any, **kwargs: Any):
        super(CreateUserForm, self).__init__(*args, **kwargs)

        for fieldname in ["username", "email", "password1", "password2"]:
            self.fields[fieldname].help_text = None 


class FlightSearchForm(forms.Form):
    origin = forms.CharField(max_length=3, min_length=3, required=True)
    destination = forms.CharField(max_length=3, min_length=3, required=True)
    departure_date = forms.DateField(required=True)
    return_date = forms.DateField(required=False)
    adults = forms.IntegerField(min_value=1, max_value=9, initial=1)
    children = forms.IntegerField(min_value=0, max_value=8, initial=0)
    infants = forms.IntegerField(min_value=0, max_value=9, initial=0)
    travel_class = forms.ChoiceField(
        choices=[
            ('ECONOMY', 'Economy'),
            ('PREMIUM_ECONOMY', 'Premium Economy'),
            ('BUSINESS', 'Business'),
            ('FIRST', 'First Class'),
        ],
        initial='ECONOMY'
    )
    currency = forms.ChoiceField(
        choices=[
            ('USD', 'US Dollar'),
            ('EUR', 'Euro'),
            ('GBP', 'British Pound'),
        ],
        initial='USD'
    )

class PassengerForm(forms.Form):
    class Meta:
        model = CustomUser
        fields = [
            'first_name',
            'last_name',
            'date_of_birth',
            'gender',
            'phone_number',
            'passport_number',
            'passport_expiry',
            'nationality'
        ]
    def validate_phone_number(value):
        """
        Validate phone number for Amadeus API
        """
        # Remove all non-digit characters
        digits = re.sub(r'\D', '', value)
        
        # Check length and format
        if not digits.isdigit():
            raise ValidationError('Phone number must contain only digits')
        
        # Adjust length requirements based on your needs
        if len(digits) < 10 or len(digits) > 15:
            raise ValidationError('Phone number must be between 10-15 digits')
        
        return digits

# class ContactForm(forms.Form):
#     email = forms.EmailField(required=True)
#     phone = forms.CharField(max_length=20, required=True)
#     address = forms.CharField(widget=forms.Textarea, required=False)