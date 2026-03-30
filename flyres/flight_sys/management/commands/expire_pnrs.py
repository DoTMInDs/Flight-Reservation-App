# management/commands/expire_pnrs.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.conf import settings
import requests
import logging
from datetime import timedelta

from flyres.flight_sys.core_backend.models import AuditLog, Reservation

# Set up logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Expire HOLD reservations that have passed their expiry time'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be expired without making changes'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Number of reservations to process at once (default: 100)'
        )
        parser.add_argument(
            '--grace-period',
            type=int,
            default=0,
            help='Grace period in minutes to add to expiry time (default: 0)'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        batch_size = options['batch_size']
        grace_period = options['grace_period']
        
        # Calculate expiry cutoff with grace period
        cutoff_time = timezone.now()
        if grace_period > 0:
            cutoff_time = cutoff_time - timedelta(minutes=grace_period)
        
        self.stdout.write(f"Starting PNR expiry process...")
        self.stdout.write(f"Dry run: {dry_run}")
        self.stdout.write(f"Batch size: {batch_size}")
        self.stdout.write(f"Grace period: {grace_period} minutes")
        self.stdout.write(f"Cutoff time: {cutoff_time}")
        
        # 1. Find expired reservations
        expired_reservations = Reservation.objects.filter(
            status='HOLD',
            expires_at__lte=cutoff_time
        ).select_related('user').order_by('expires_at')[:batch_size]
        
        expired_count = expired_reservations.count()
        
        if expired_count == 0:
            self.stdout.write(self.style.SUCCESS("No expired reservations found."))
            return
        
        self.stdout.write(f"Found {expired_count} expired reservation(s) to process.")
        
        success_count = 0
        failure_count = 0
        skipped_count = 0
        
        for reservation in expired_reservations:
            try:
                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Would expire: PNR {reservation.gds_reference} "
                        f"for user {reservation.user.email if reservation.user else 'N/A'} "
                        f"(expired at: {reservation.expires_at})"
                    )
                    skipped_count += 1
                    continue
                
                # Process each reservation in its own transaction
                result = self.process_reservation(reservation)
                
                if result:
                    success_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Successfully expired PNR: {reservation.gds_reference}"
                        )
                    )
                else:
                    failure_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Failed to expire PNR: {reservation.gds_reference}"
                        )
                    )
                    
            except Exception as e:
                failure_count += 1
                logger.error(f"Error processing reservation {reservation.id}: {str(e)}", 
                           exc_info=True)
                self.stdout.write(
                    self.style.ERROR(
                        f"Error processing PNR {reservation.gds_reference}: {str(e)}"
                    )
                )
        
        # Summary
        self.stdout.write("\n" + "="*50)
        self.stdout.write("PROCESSING SUMMARY:")
        self.stdout.write(f"Total found: {expired_count}")
        self.stdout.write(f"Successfully expired: {success_count}")
        self.stdout.write(f"Failed: {failure_count}")
        
        if dry_run:
            self.stdout.write(f"Skipped (dry run): {skipped_count}")
            self.stdout.write(self.style.WARNING("DRY RUN COMPLETED - No changes were made"))
        else:
            if failure_count == 0:
                self.stdout.write(self.style.SUCCESS("SUCCESS: All reservations processed successfully"))
            else:
                self.stdout.write(self.style.WARNING(f"WARNING: {failure_count} reservation(s) failed to process"))
    
    @transaction.atomic
    def process_reservation(self, reservation):
        """Process a single reservation expiration"""
        try:
            # 2. Cancel in GDS (if GDS reference exists)
            gds_cancelled = True
            if reservation.gds_reference:
                gds_cancelled = self.cancel_in_gds(reservation)
                
                if not gds_cancelled:
                    logger.warning(
                        f"GDS cancellation failed for PNR {reservation.gds_reference}, "
                        f"but marking as expired locally"
                    )
            
            # 3. Update status
            reservation.status = 'EXPIRED'
            reservation.expired_at = timezone.now()
            reservation.save()
            
            # 4. Log for compliance
            AuditLog.objects.create(
                reservation=reservation,
                action='PNR_EXPIRE',
                details={
                    'reason': 'automatic_expiry',
                    'gds_cancelled': gds_cancelled,
                    'gds_reference': reservation.gds_reference,
                    'expired_at': timezone.now().isoformat()
                }
            )
            
            # 5. Notify user (optional)
            if reservation.user and reservation.user.email:
                try:
                    self.send_expiry_notification(reservation)
                except Exception as e:
                    logger.error(f"Failed to send expiry notification for reservation {reservation.id}: {str(e)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to process reservation {reservation.id}: {str(e)}", exc_info=True)
            raise
    
    def cancel_in_gds(self, reservation):
        """Cancel PNR in GDS to free inventory"""
        try:
            # Get Amadeus token
            token = self.get_amadeus_token()
            if not token:
                logger.error("Failed to obtain Amadeus token")
                return False
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            # Amadeus cancel endpoint
            response = requests.delete(
                f'https://api.amadeus.com/v1/booking/flight-orders/{reservation.gds_reference}',
                headers=headers,
                timeout=30  # Add timeout
            )
            
            if response.status_code == 200:
                logger.info(f"Successfully cancelled PNR {reservation.gds_reference} in GDS")
                return True
            else:
                logger.error(
                    f"GDS cancellation failed for PNR {reservation.gds_reference}. "
                    f"Status: {response.status_code}, Response: {response.text}"
                )
                return False
                
        except requests.exceptions.Timeout:
            logger.error(f"GDS cancellation timeout for PNR {reservation.gds_reference}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during GDS cancellation for PNR {reservation.gds_reference}: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during GDS cancellation: {str(e)}")
            return False
    
    def get_amadeus_token(self):
        """
        Get Amadeus API token
        In production, you might want to cache this token
        """
        try:
            # This should be moved to a separate service or use Django cache
            # For now, implement a simple token retrieval
            response = requests.post(
                'https://api.amadeus.com/v1/security/oauth2/token',
                data={
                    'grant_type': 'client_credentials',
                    'client_id': settings.AMADEUS_API_KEY,
                    'client_secret': settings.AMADEUS_API_SECRET
                },
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json().get('access_token')
            else:
                logger.error(f"Failed to get Amadeus token: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting Amadeus token: {str(e)}")
            return None
    
    def send_expiry_notification(self, reservation):
        """Send expiry notification to user"""
        # Implement your notification logic here
        # This could be email, SMS, push notification, etc.
        
        # Example email sending (pseudo-code):
        # subject = "Your Reservation Has Expired"
        # message = f"Your reservation {reservation.gds_reference} has expired."
        # send_mail(subject, message, 'noreply@example.com', [reservation.user.email])
        
        logger.info(f"Notification sent for expired reservation {reservation.gds_reference} to {reservation.user.email}")