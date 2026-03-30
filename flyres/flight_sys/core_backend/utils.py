# flight_sys/core_backend/utils.py
from django.core.mail import send_mail
from django.conf import settings
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def send_welcome_email(user):
    """Send welcome email to new user"""
    try:
        subject = 'Welcome to Flight Reservation System'
        message = f"""
        Hi {user.username},
        
        Welcome to Flight Reservation System! We're excited to have you on board.
        
        You can now:
        - Search and book flights
        - Manage your bookings
        - Get real-time flight information
        
        Happy travels!
        
        The FlightReserve Team
        """
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
        logger.info(f"Welcome email sent to {user.email}")
        
    except Exception as e:
        logger.error(f"Failed to send welcome email: {str(e)}")

def validate_search_params(get_params):
    """Validate and normalize flight search parameters"""
    try:
        params = {
            'origin': get_params.get('origin', '').strip().upper(),
            'destination': get_params.get('destination', '').strip().upper(),
            'departure_date': get_params.get('departure_date', '').strip(),
            'return_date': get_params.get('return_date', '').strip() or None,
            'adults': int(get_params.get('adults', 1)),
            'children': int(get_params.get('children', 0)),
            'infants': int(get_params.get('infants', 0)),
            'travel_class': get_params.get('travel_class', 'ECONOMY').upper(),
            'currency': get_params.get('currency', 'USD').upper(),
            'non_stop': get_params.get('nonstop') == 'true',
            'max_results': int(get_params.get('max_results', 50)),
        }
        
        # Basic validation
        if len(params['origin']) != 3:
            return None
        
        if len(params['destination']) != 3:
            return None
        
        if not params['departure_date']:
            return None
        
        # Validate dates
        try:
            datetime.strptime(params['departure_date'], '%Y-%m-%d')
            if params['return_date']:
                datetime.strptime(params['return_date'], '%Y-%m-%d')
        except ValueError:
            return None
        
        # Validate passenger counts
        if params['adults'] < 1 or params['adults'] > 9:
            return None
        
        if params['children'] < 0 or params['children'] > 8:
            return None
        
        if params['infants'] < 0 or params['infants'] > params['adults']:
            return None
        
        return params
        
    except (ValueError, KeyError) as e:
        logger.error(f"Search validation error: {str(e)}")
        return None

def format_duration(duration_str):
    """Format ISO duration string to readable format"""
    if not duration_str:
        return ''
    
    # PT5H30M -> 5h 30m
    duration = duration_str.replace('PT', '')
    hours = ''
    minutes = ''
    
    if 'H' in duration:
        hours_part = duration.split('H')[0]
        hours = f"{hours_part}h "
        duration = duration.split('H')[1] if 'H' in duration else duration
    
    if 'M' in duration:
        minutes_part = duration.split('M')[0]
        minutes = f"{minutes_part}m"
    
    return f"{hours}{minutes}".strip()

def duration_to_minutes(duration_str):
    """Convert ISO duration to minutes"""
    if not duration_str:
        return 0
    
    minutes = 0
    duration = duration_str.replace('PT', '')
    
    if 'H' in duration:
        hours_part = duration.split('H')[0]
        minutes += int(hours_part) * 60
        duration = duration.split('H')[1] if 'H' in duration else ''
    
    if 'M' in duration:
        minutes_part = duration.split('M')[0]
        minutes += int(minutes_part)
    
    return minutes

def format_price(price, currency='USD'):
    """Format price with currency"""
    try:
        price_float = float(price)
        return f"{currency} {price_float:.2f}"
    except:
        return f"{currency} 0.00"

def get_airline_name(iata_code):
    """Get airline name from IATA code"""
    airlines = {
        'AA': 'American Airlines',
        'DL': 'Delta Air Lines',
        'UA': 'United Airlines',
        'WN': 'Southwest Airlines',
        'B6': 'JetBlue Airways',
        'NK': 'Spirit Airlines',
        'F9': 'Frontier Airlines',
        'AS': 'Alaska Airlines',
        'HA': 'Hawaiian Airlines',
        'G4': 'Allegiant Air',
        'AC': 'Air Canada',
        'BA': 'British Airways',
        'LH': 'Lufthansa',
        'AF': 'Air France',
        'KL': 'KLM',
        'EK': 'Emirates',
        'QR': 'Qatar Airways',
        'SQ': 'Singapore Airlines',
        'CX': 'Cathay Pacific',
        'JL': 'Japan Airlines',
    }
    return airlines.get(iata_code, iata_code)

def extract_travel_class(offer_data):
    """Extract travel class from flight offer"""
    try:
        traveler_pricings = offer_data.get('travelerPricings', [])
        if traveler_pricings:
            fare_details = traveler_pricings[0].get('fareDetailsBySegment', [])
            if fare_details:
                return fare_details[0].get('cabin', 'ECONOMY')
    except:
        pass
    return 'ECONOMY'

def create_price_ranges(flights):
    """Create dynamic price ranges based on flight prices"""
    if not flights:
        return []
    
    # Extract prices
    prices = []
    for flight in flights:
        try:
            price = float(flight.get('price', {}).get('total', 0))
            prices.append(price)
        except:
            continue
    
    if not prices:
        return []
    
    min_price = min(prices)
    max_price = max(prices)
    
    # Create ranges
    ranges = []
    range_size = max(50, (max_price - min_price) / 4)
    
    for i in range(4):
        lower = int(min_price + (i * range_size))
        upper = int(min_price + ((i + 1) * range_size)) if i < 3 else 0
        
        if i < 3:
            ranges.append({
                'value': f'{lower}-{upper}',
                'label': f'${lower} - ${upper}',
                'min': lower,
                'max': upper
            })
        else:
            ranges.append({
                'value': f'{lower}-0',
                'label': f'Over ${lower}',
                'min': lower,
                'max': 0
            })
    
    return ranges

def extract_airlines(flights):
    """Extract unique airlines from flights"""
    airlines_set = set()
    
    for flight in flights:
        # Get validating airline
        validating_airline = flight.get('validating_airline', '')
        if validating_airline:
            airlines_set.add(get_airline_name(validating_airline))
        
        # Get airline names from segments
        for itinerary in flight.get('itineraries', []):
            for segment in itinerary.get('segments', []):
                airline_code = segment.get('carrierCode', '')
                if airline_code:
                    airlines_set.add(get_airline_name(airline_code))
    
    # Convert to list of dictionaries for template
    airlines = []
    for airline_name in sorted(airlines_set):
        airlines.append({
            'code': airline_name[:3].upper(),
            'name': airline_name
        })
    
    return airlines