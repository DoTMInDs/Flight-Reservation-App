"""
Celery tasks for flight reservation system
"""
from celery import shared_task
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
import requests
import logging
from django.conf import settings

from .models import Reservation, AuditLog
from .utils import get_amadeus_token, send_expiry_warning

logger = logging.getLogger(__name__)

@shared_task
def monitor_pnr_expirations():
    """
    Run every 5 minutes to:
    1. Send warnings for reservations expiring soon
    2. Cancel expired reservations in GDS
    """
    now = timezone.now()
    
    # 1. Check reservations expiring soon (send warnings)
    warning_threshold = now + timedelta(hours=2)
    
    soon_expiring = Reservation.objects.filter(
        status='HOLD',
        expires_at__lte=warning_threshold,
        expires_at__gt=now,
        warning_sent=False
    ).select_related('flight_offer')
    
    for reservation in soon_expiring:
        try:
            send_expiry_warning(reservation)
            reservation.warning_sent = True
            reservation.save()
            
            logger.info(f"Expiry warning sent for PNR: {reservation.pnr}")
        except Exception as e:
            logger.error(f"Failed to send expiry warning for PNR {reservation.pnr}: {e}")
    
    # 2. Cancel expired reservations
    expired_reservations = Reservation.objects.filter(
        status='HOLD',
        expires_at__lte=now
    ).select_for_update(skip_locked=True)
    
    for reservation in expired_reservations:
        cancel_expired_pnr.delay(reservation.id)
    
    return f"Processed {soon_expiring.count()} warnings and {expired_reservations.count()} expirations"

@shared_task
def cancel_expired_pnr(reservation_id):
    """
    Cancel an expired PNR in GDS and update status
    """
    try:
        with transaction.atomic():
            reservation = Reservation.objects.select_for_update().get(
                id=reservation_id,
                status='HOLD'
            )
            
            # Skip if already expired by another process
            if reservation.expires_at > timezone.now():
                return
            
            # Cancel in GDS
            headers = {
                'Authorization': f'Bearer {get_amadeus_token()}',
                'Content-Type': 'application/json'
            }
            
            try:
                response = requests.delete(
                    f'https://test.api.amadeus.com/v1/booking/flight-orders/{reservation.gds_reference}',
                    headers=headers,
                    timeout=10
                )
                
                if response.status_code in [200, 204]:
                    logger.info(f"Successfully cancelled PNR {reservation.pnr} in GDS")
                else:
                    logger.warning(f"GDS cancellation returned {response.status_code} for PNR {reservation.pnr}")
            
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to cancel PNR {reservation.pnr} in GDS: {e}")
                # Continue with status update even if GDS cancellation fails
            
            # Update status
            reservation.status = 'EXPIRED'
            reservation.save()
            
            # Log the expiration
            AuditLog.objects.create(
                reservation=reservation,
                action='PNR_EXPIRE',
                details={
                    'reason': 'automatic_expiry',
                    'expired_at': timezone.now().isoformat(),
                    'gds_cancellation_success': response.status_code in [200, 204] if 'response' in locals() else False
                }
            )
            
            logger.info(f"PNR {reservation.pnr} marked as expired")
    
    except Reservation.DoesNotExist:
        logger.warning(f"Reservation {reservation_id} not found or already processed")
    except Exception as e:
        logger.exception(f"Error cancelling PNR for reservation {reservation_id}: {e}")

@shared_task
def send_itinerary_email(reservation_id):
    """
    Send itinerary PDF via email
    """
    from django.core.mail import EmailMessage
    from .models import Itinerary
    
    try:
        reservation = Reservation.objects.get(id=reservation_id)
        itinerary = Itinerary.objects.get(reservation=reservation)
        
        subject = f'Your Flight Itinerary - PNR: {reservation.pnr}'
        
        email = EmailMessage(
            subject=subject,
            body=f'Please find your flight itinerary attached. PNR: {reservation.pnr}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[reservation.contact_email],
        )
        
        # Attach PDF
        itinerary.pdf_file.seek(0)
        email.attach(
            f'itinerary_{reservation.pnr}.pdf',
            itinerary.pdf_file.read(),
            'application/pdf'
        )
        
        email.send()
        
        # Update sent status
        itinerary.email_sent = True
        itinerary.sent_at = timezone.now()
        itinerary.save()
        
        # Log the email send
        AuditLog.objects.create(
            reservation=reservation,
            action='EMAIL_SENT',
            details={'sent_to': reservation.contact_email}
        )

        logger.info(f"Itinerary email sent for PNR: {reservation.pnr}")
    except Exception as e:
        logger.error(f"Failed to send itinerary email for reservation {reservation_id}: {e}")