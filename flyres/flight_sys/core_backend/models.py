# models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
import json


class GenderChoices(models.TextChoices):
    MALE = 'MALE', 'Male'
    FEMALE = 'FEMALE', 'Female'
    OTHER = 'OTHER', 'Other'

class CustomUser(AbstractUser):
    """Extended user model"""
    phone_number = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=GenderChoices.choices, default=GenderChoices.OTHER)
    nationality = models.CharField(max_length=2, default='GH')
    passport_number = models.CharField(max_length=20, blank=True)
    passport_expiry = models.DateField(null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'custom_user'
    
    def __str__(self):
        return self.email or self.username

class FlightOffer(models.Model):
    """Store flight offers from Amadeus"""
    offer_id = models.CharField(max_length=100, unique=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='flight_offers')
    offer_data = models.JSONField()  # Full Amadeus offer JSON
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=3, default='USD')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_priced = models.BooleanField(default=False)
    priced_data = models.JSONField(null=True, blank=True)  # Priced offer data
    
    class Meta:
        ordering = ['-created_at']
    
    def is_expired(self):
        return timezone.now() > self.expires_at
    
    def get_summary(self):
        """Extract summary from offer data"""
        try:
            data = self.offer_data
            itineraries = data.get('itineraries', [])
            if itineraries:
                first_itinerary = itineraries[0]
                first_segment = first_itinerary.get('segments', [{}])[0]
                last_segment = first_itinerary.get('segments', [{}])[-1]
                
                return {
                    'origin': first_segment.get('departure', {}).get('iataCode', ''),
                    'destination': last_segment.get('arrival', {}).get('iataCode', ''),
                    'departure': first_segment.get('departure', {}).get('at', ''),
                    'airline': first_segment.get('carrierCode', ''),
                    'flight_number': first_segment.get('number', ''),
                }
        except:
            pass
        return {}

class Reservation(models.Model):
    """Flight reservation/booking"""
    STATUS_CHOICES = [
        ('HOLD', 'On Hold'),
        ('CONFIRMED', 'Confirmed'),
        ('TICKETED', 'Ticketed'),
        ('EXPIRED', 'Expired'),
        ('CANCELLED', 'Cancelled'),
        ('VOIDED', 'Voided'),
    ]
    
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='reservations')
    gds_reference = models.CharField(max_length=50)  # Amadeus order ID
    airline_pnr = models.CharField(max_length=10)  # Airline PNR
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='HOLD')
    expires_at = models.DateTimeField()
    expired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Flight details
    flight_details = models.JSONField()  # Full booking response from Amadeus
    passenger_details = models.JSONField()  # List of travelers
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=20, blank=True)
    
    # Pricing
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    base_fare = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    taxes = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    fees = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    
    # Ticketing
    ticket_number = models.CharField(max_length=20, blank=True)
    ticket_issue_date = models.DateTimeField(null=True, blank=True)
    ticket_deadline = models.DateTimeField(null=True, blank=True)
    
    # Payment
    payment_reference = models.CharField(max_length=100, blank=True)
    payment_status = models.CharField(max_length=20, default='PENDING')
    
    # Cancellation
    cancellation_reason = models.TextField(blank=True)
    cancellation_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status', 'expires_at']),
            models.Index(fields=['airline_pnr']),
            models.Index(fields=['gds_reference']),
        ]
    
    def __str__(self):
        return f"{self.airline_pnr} - {self.user.email}"
    
    def is_expired(self):
        return self.status == 'EXPIRED' or (timezone.now() > self.expires_at and self.status == 'HOLD')
    
    def get_flight_summary(self):
        """Extract flight summary from booking data"""
        try:
            flight_offers = self.flight_details.get('flightOffers', [])
            if flight_offers:
                offer = flight_offers[0]
                itineraries = offer.get('itineraries', [])
                if itineraries:
                    first_itinerary = itineraries[0]
                    segments = first_itinerary.get('segments', [])
                    if segments:
                        first_segment = segments[0]
                        last_segment = segments[-1]
                        
                        return {
                            'origin': first_segment.get('departure', {}).get('iataCode', ''),
                            'destination': last_segment.get('arrival', {}).get('iataCode', ''),
                            'departure': first_segment.get('departure', {}).get('at', ''),
                            'arrival': last_segment.get('arrival', {}).get('at', ''),
                            'airline': first_segment.get('carrierCode', ''),
                            'flight_number': f"{first_segment.get('carrierCode', '')}{first_segment.get('number', '')}",
                            'duration': first_itinerary.get('duration', ''),
                            'stops': len(segments) - 1,
                        }
        except:
            pass
        return {}
    
    def get_passenger_count(self):
        """Get number of passengers"""
        try:
            return len(self.passenger_details)
        except:
            return 0

class AuditLog(models.Model):
    """Audit trail for all reservations"""
    ACTION_CHOICES = [
        ('SEARCH', 'Flight Search'),
        ('OFFER_SELECT', 'Offer Selected'),
        ('PRICING', 'Flight Priced'),
        ('BOOKING_CREATED', 'Booking Created'),
        ('BOOKING_CONFIRMED', 'Booking Confirmed'),
        ('TICKET_ISSUED', 'Ticket Issued'),
        ('BOOKING_EXPIRED', 'Booking Expired'),
        ('BOOKING_CANCELLED', 'Booking Cancelled'),
        ('BOOKING_UPDATED', 'Booking Updated'),
        ('PNR_RETRIEVED', 'PNR Retrieved'),
        ('PAYMENT_INITIATED', 'Payment Initiated'),
        ('PAYMENT_COMPLETED', 'Payment Completed'),
        ('PAYMENT_FAILED', 'Payment Failed'),
    ]
    
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name='audit_logs', null=True)
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    details = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reservation', 'action']),
            models.Index(fields=['user', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_action_display()} - {self.created_at}"