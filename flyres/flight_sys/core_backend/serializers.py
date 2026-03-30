"""
Serializers for flight reservation system
"""
from rest_framework import serializers
from django.utils import timezone
from datetime import datetime

class FlightSearchSerializer(serializers.Serializer):
    origin = serializers.CharField(max_length=3, required=True)
    destination = serializers.CharField(max_length=3, required=True)
    date = serializers.DateField(required=True)
    return_date = serializers.DateField(required=False)
    adults = serializers.IntegerField(min_value=1, max_value=9, default=1)
    children = serializers.IntegerField(min_value=0, max_value=9, default=0)
    infants = serializers.IntegerField(min_value=0, max_value=9, default=0)
    max_results = serializers.IntegerField(min_value=1, max_value=250, default=50)
    
    def validate(self, data):
        # Validate date is not in the past
        if data['date'] < timezone.now().date():
            raise serializers.ValidationError("Departure date cannot be in the past")
        
        # Validate return date if provided
        if 'return_date' in data and data['return_date'] < data['date']:
            raise serializers.ValidationError("Return date must be after departure date")
        
        # Validate airport codes (basic check)
        if len(data['origin']) != 3 or len(data['destination']) != 3:
            raise serializers.ValidationError("Airport codes must be 3 letters")
        
        return data

class PassengerSerializer(serializers.Serializer):
    id = serializers.CharField(required=True)
    dateOfBirth = serializers.DateField(required=True)
    name = serializers.DictField(required=True)
    gender = serializers.ChoiceField(choices=['MALE', 'FEMALE', 'UNDEFINED'])
    contact = serializers.DictField(required=True)
    documents = serializers.ListField(child=serializers.DictField(), required=False)
    
    def validate_dateOfBirth(self, value):
        if value > timezone.now().date():
            raise serializers.ValidationError("Date of birth cannot be in the future")
        return value

class ContactInfoSerializer(serializers.Serializer):
    addressee_name = serializers.DictField(required=True)
    email = serializers.EmailField(required=True)
    phones = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
        required=True
    )

class BookingSerializer(serializers.Serializer):
    flight_offer_id = serializers.IntegerField(required=True)
    passengers = serializers.ListField(
        child=PassengerSerializer(),
        min_length=1,
        max_length=9,
        required=True
    )
    contact_info = ContactInfoSerializer(required=True)