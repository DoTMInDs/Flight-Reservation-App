from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import datetime, timedelta
import json
import logging
from django.http import JsonResponse, HttpResponse
import re
# import datetime
from core_backend.services.amadeus_service import AmadeusService, NoFlightsError, FareRuleError, SoldOutError
from core_backend.services.location_service import LocationService 
from .models import Reservation,FlightOffer
from .forms import CreateUserForm
from .utils import send_welcome_email
# from .services.amadeus_service import amadeus_service
amadeus_service = AmadeusService()
from .utils import send_welcome_email, validate_search_params
from .pdf_generator import ReportLabPDFGenerator, WeasyPrintPDFGenerator
from .amadeus_itinerary_generator import AmadeusOfficialItineraryGenerator
from django.core.cache import cache

logger = logging.getLogger(__name__)

def home(request):
    """Home page"""
    return render(request, 'core/routes/home.html')

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f'Welcome back, {username}!')
            return redirect('home')
        else:
            messages.error(request, 'Invalid username or password.')
            return redirect('login')
    return render(request, 'core/accounts/registration/login.html')

def logout_view(request):
    """Custom logout view"""
    logout(request)
    messages.success(request, "Logged Out successfully!!")
    return redirect('home')

def register_view(request):
    """Custom registration view"""
    form = CreateUserForm()
    if request.method == 'POST':
        form = CreateUserForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.isactive = True  # In production, set to False until email verification
            user.is_verified = True
            user.save()

            # Send welcome email
            try:
                send_welcome_email(user)
            except Exception as e:
                # Log the error but don't prevent registration
                print(f"Error sending welcome email: {e}")

            messages.success(request, f'Account created for {user.username}. You can now log in.')
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password1')
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('home')
            else:
                messages.error(request, 'Authentication failed. Please log in manually.')
                return redirect('login')
            
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

    context = {'form': form}
    return render(request, 'core/accounts/registration/register.html', context)

@login_required
def profile_view(request):
    """User profile view"""
    user = request.user
    
    if request.method == 'POST':
        # Update user profile
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.email = request.POST.get('email', user.email)
        user.phone_number = request.POST.get('phone_number', user.phone_number)
        
        # Handle optional fields
        dob = request.POST.get('date_of_birth')
        user.date_of_birth = datetime.strptime(dob, '%Y-%m-%d').date() if dob else None
        
        user.gender = request.POST.get('gender', user.gender)
        user.nationality = request.POST.get('nationality', user.nationality)
        user.passport_number = request.POST.get('passport_number', user.passport_number)
        
        passport_expiry = request.POST.get('passport_expiry')
        user.passport_expiry = datetime.strptime(passport_expiry, '%Y-%m-%d').date() if passport_expiry else None
        
        user.save()
        messages.success(request, 'Profile updated successfully!')
        return redirect('profile')
    
    # Calculate stats for template
    total_bookings = user.reservations.count()
    active_holds = user.reservations.filter(status='HOLD').count()
    
    context = {
        'user': user,
        'stats': {
            'total_bookings': total_bookings,
            'active_holds': active_holds,
        }
    }
    
    return render(request, 'core/accounts/registration/profile.html', context)


def suggest_alternative_dates(original_date_str, days_to_check=3):
    """Suggest alternative dates when one fails"""
    try:
        base_date = datetime.datetime.strptime(original_date_str, "%Y-%m-%d")
        today = datetime.datetime.now()
        
        alternatives = []
        
        # Check future dates first (more likely to have availability)
        for offset in range(1, days_to_check + 1):
            new_date = base_date + datetime.timedelta(days=offset)
            # Don't suggest dates too far in the future (Amadeus limit)
            if new_date <= today + datetime.timedelta(days=330):
                alternatives.append({
                    'date': new_date.strftime("%Y-%m-%d"),
                    'day_of_week': new_date.strftime("%A"),
                    'offset': offset,
                    'direction': 'later'
                })
        
        # Then check past dates
        for offset in range(1, days_to_check + 1):
            new_date = base_date - datetime.timedelta(days=offset)
            # Don't suggest dates in the past
            if new_date >= today:
                alternatives.append({
                    'date': new_date.strftime("%Y-%m-%d"),
                    'day_of_week': new_date.strftime("%A"),
                    'offset': offset,
                    'direction': 'earlier'
                })
        
        # Sort by closest date first
        alternatives.sort(key=lambda x: x['offset'])
        return alternatives[:5]  # Return max 5 alternatives
    except ValueError:
        return []

def create_retry_search_params(search_params, new_date):
    """Create new search params with alternative date"""
    retry_params = search_params.copy()
    retry_params['departure_date'] = new_date
    retry_params['_retry_original_date'] = search_params.get('departure_date')
    retry_params['_retry_attempt'] = search_params.get('_retry_attempt', 0) + 1
    return retry_params

def get_date_error_suggestion(original_date, error_message):
    """Generate user-friendly date suggestions"""
    suggestions = []
    alt_dates = suggest_alternative_dates(original_date)
    
    for alt in alt_dates:
        suggestion = {
            'date': alt['date'],
            'display': f"{alt['date']} ({alt['day_of_week']})",
            'description': f"{alt['offset']} day{'s' if alt['offset'] > 1 else ''} {alt['direction']}"
        }
        suggestions.append(suggestion)
    
    return suggestions
# ========== END HELPER FUNCTIONS ==========


@login_required
def flight_search(request):
    """Flight search page with airport autocomplete and location detection"""
    # Get popular airports for suggestions
    popular_airports = [
        {'code': 'JFK', 'name': 'John F. Kennedy', 'city': 'New York'},
        {'code': 'LAX', 'name': 'Los Angeles', 'city': 'Los Angeles'},
        {'code': 'ORD', 'name': "O'Hare", 'city': 'Chicago'},
        {'code': 'DFW', 'name': 'Dallas/Fort Worth', 'city': 'Dallas'},
        {'code': 'MIA', 'name': 'Miami', 'city': 'Miami'},
        {'code': 'ATL', 'name': 'Hartsfield-Jackson', 'city': 'Atlanta'},
        {'code': 'LHR', 'name': 'Heathrow', 'city': 'London'},
        {'code': 'CDG', 'name': 'Charles de Gaulle', 'city': 'Paris'},
        {'code': 'DXB', 'name': 'Dubai', 'city': 'Dubai'},
        {'code': 'HND', 'name': 'Haneda', 'city': 'Tokyo'},
        # african popular airports
        {'code': 'JNB', 'name': 'O.R. Tambo International', 'city': 'Johannesburg'},
        {'code': 'LOS', 'name': 'Murtala Muhammed International', 'city': 'Lagos'},
        {'code': 'CAI', 'name': 'Cairo International', 'city': 'Cairo'},
        {'code': 'NBO', 'name': 'Jomo Kenyatta International', 'city': 'Nairobi'},
        {'code': 'ACC', 'name': 'Kotoka International', 'city': 'Accra'},
    ]
    
    # Detect user location
    location_service = LocationService()
    location_context = location_service.get_location_context(request)
    
    # Get detected airport (main airport for country or nearest)
    detected_airport = None
    if location_context['main_airport_code']:
        detected_airport = {
            'code': location_context['main_airport_code'],
            'name': f"Main airport in {location_context['detected_country']}",
            'city': location_context['detected_city'],
            'country': location_context['detected_country'],
            'is_detected': True,
        }
    elif location_context['nearest_airports']:
        nearest = location_context['nearest_airports'][0]
        detected_airport = {
            'code': nearest['code'],
            'name': nearest['name'],
            'city': nearest['city'],
            'country': nearest['country'],
            'is_detected': True,
        }
    
    context = {
        'popular_airports': popular_airports,
        'today': datetime.now().strftime('%Y-%m-%d'),
        'max_date': (datetime.now() + timedelta(days=330)).strftime('%Y-%m-%d'),
        'detected_location': location_context['user_location'],
        'detected_airport': detected_airport,
        'nearest_airports': location_context['nearest_airports'][:3],  # Top 3 nearest
    }
    return render(request, 'core/routes/search.html', context)


@login_required
def flight_search_results(request):
    """Display real flight search results from Amadeus API"""
    try:
        # Validate and parse search parameters
        search_params = validate_search_params(request.GET)
        if not search_params:
            messages.error(request, 'Invalid search parameters')
            return redirect('flight_search')
        
        # Generate cache key (excluding retry parameters for caching)
        cache_params = search_params.copy()
        cache_params.pop('_retry_original_date', None)
        cache_params.pop('_retry_attempt', None)
        cache_key = f"flight_search_{request.user.id}_{hash(frozenset(cache_params.items()))}"
        
        # Try cache first (only if not a retry attempt)
        retry_attempt = search_params.get('_retry_attempt', 0)
        cached_results = None if retry_attempt > 0 else cache.get(cache_key)
        
        if cached_results:
            flights, search_summary = cached_results
            messages.info(request, f"Showing cached results from {search_summary['cached_at']}")
        else:
            # Call Amadeus API
            try:
                flights, error = amadeus_service.search_flight_offers(search_params)
                
                if error:
                    logger.error(f"Flight search API error: {error}")
                    raise Exception(error)
                
            except NoFlightsError as e:
                # Handle no flights error
                original_date = search_params.get('departure_date')
                alternative_dates = suggest_alternative_dates(original_date)
                
                # Check if this is already a retry
                if retry_attempt > 0:
                    messages.error(request, 
                        f"No flights available for {original_date} or nearby dates. "
                        f"Please try different dates."
                    )
                else:
                    messages.warning(request, 
                        f"No flights found for {original_date}. "
                        f"Try one of the alternative dates below."
                    )
                
                context = {
                    'search_params': search_params,
                    'flights': [],
                    'error': str(e),
                    'alternative_dates': alternative_dates,
                    'show_retry_suggestions': True,
                    'original_date': original_date,
                }
                return render(request, 'core/routes/results.html', context)
                
            except FareRuleError as e:
                # Handle fare rule errors
                original_date = search_params.get('departure_date')
                alternative_dates = suggest_alternative_dates(original_date)
                
                messages.warning(request, 
                    f"Fare rules not met for {original_date}. "
                    f"Try adjusting your dates by 1-2 days."
                )
                
                context = {
                    'search_params': search_params,
                    'flights': [],
                    'error': str(e),
                    'alternative_dates': alternative_dates,
                    'show_retry_suggestions': True,
                    'original_date': original_date,
                    'error_type': 'fare_rule'
                }
                return render(request, 'core/routes/results.html', context)
                
            except SoldOutError as e:
                # Handle sold out errors
                original_date = search_params.get('departure_date')
                alternative_dates = suggest_alternative_dates(original_date)
                
                messages.warning(request, 
                    f"Flights sold out for {original_date}. "
                    f"Try alternative dates for better availability."
                )
                
                context = {
                    'search_params': search_params,
                    'flights': [],
                    'error': str(e),
                    'alternative_dates': alternative_dates,
                    'show_retry_suggestions': True,
                    'original_date': original_date,
                    'error_type': 'sold_out'
                }
                return render(request, 'core/routes/results.html', context)
            
            if not flights:
                # Generic no flights case
                original_date = search_params.get('departure_date')
                alternative_dates = suggest_alternative_dates(original_date)
                
                messages.info(request, 
                    f'No flights found for {original_date}.'
                )
                
                context = {
                    'search_params': search_params,
                    'flights': [],
                    'error': 'No flights found for selected criteria',
                    'alternative_dates': alternative_dates,
                    'show_retry_suggestions': True,
                    'original_date': original_date,
                }
                return render(request, 'core/routes/results.html', context)
            
            # ========== ADDED FIX ==========
            # Add offer_json to each flight for the template form
            for flight in flights:
                # Convert the entire flight object to JSON string for the form
                flight['offer_json'] = json.dumps(flight)
            # ========== END FIX ==========
            
            # Prepare search summary
            search_summary = {
                'total_found': len(flights),
                'currency': flights[0]['price']['currency'] if flights else 'USD',
                'cached_at': timezone.now().strftime('%H:%M:%S'),
                'departure_date': search_params.get('departure_date'),
            }
            
            # Cache results for 5 minutes (only if successful)
            cache.set(cache_key, (flights, search_summary), 300)
        
        # Prepare filters
        airlines_set = set()
        price_range = {'min': float('inf'), 'max': 0}
        
        for flight in flights:
            # Collect airlines (use the processed airline_names)
            for airline in flight.get('airline_names', []):
                airlines_set.add(airline)
            
            # Calculate price range
            try:
                price = float(flight['price']['total'])
                price_range['min'] = min(price_range['min'], price)
                price_range['max'] = max(price_range['max'], price)
            except:
                pass
        
        # Create price ranges
        price_ranges = create_price_ranges(price_range)
        
        # Create airline filters
        airlines = []
        for airline_name in airlines_set:
            # Extract code from name or use first 2 characters
            code = airline_name[:3].upper() if airline_name else ''
            airlines.append({'code': code, 'name': airline_name})
        airlines = sorted(airlines, key=lambda x: x['name'])
        
        context = {
            'search_params': search_params,
            'flights': flights,
            'search_summary': search_summary,
            'price_ranges': price_ranges,
            'airlines': airlines,
            'total_flights': len(flights),
            'retry_attempt': retry_attempt,
            'original_date': search_params.get('_retry_original_date', search_params.get('departure_date')),
        }
        
        return render(request, 'core/routes/results.html', context)
        
    except Exception as e:
        logger.error(f"Flight search error: {str(e)}", exc_info=True)
        messages.error(request, 'An error occurred while searching for flights. Please try again.')
        return redirect('flight_search')
    

def create_price_ranges(price_range):  # Fixed: removed self parameter
    """Create dynamic price ranges based on search results"""
    if price_range['max'] <= 0:
        return []
    
    ranges = []
    min_price = max(0, int(price_range['min']))
    max_price = int(price_range['max'])
    
    # Create 4 ranges
    range_size = max(50, (max_price - min_price) // 4)
    
    for i in range(4):
        lower = min_price + (i * range_size)
        upper = min_price + ((i + 1) * range_size) if i < 3 else 0
        
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

# ==================== FLIGHT SELECTION ====================

@login_required
def select_flight(request):
    """Handle flight selection with pricing validation"""
    if request.method != 'POST':
        return redirect('flight_search')
    
    try:
        offer_id = request.POST.get('offer_id')
        price = request.POST.get('price')
        offer_json = request.POST.get('offer_json')  # Full offer JSON from Amadeus
        
        if not all([offer_id, price, offer_json]):
            messages.error(request, 'Missing flight information')
            return redirect('flight_search_results')
        
        # Parse and validate offer
        try:
            offer_data = json.loads(offer_json)
            if not isinstance(offer_data, dict) or 'id' not in offer_data:
                raise ValueError("Invalid offer data")
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Invalid flight offer data: {str(e)}")
            messages.error(request, 'Invalid flight data')
            return redirect('flight_search_results')
        
        # **CRITICAL: Use the original Amadeus data for pricing if available**
        # The processed flight data has custom fields that break the Amadeus API
        pricing_data = offer_data
        
        # Check if we have the original Amadeus data stored separately
        if '_original_amadeus_data' in offer_data:
            pricing_data = offer_data['_original_amadeus_data']
            logger.info(f"Using _original_amadeus_data for pricing (clean Amadeus format)")
        else:
            logger.info(f"No _original_amadeus_data found, using provided data")
            
            # Try to clean up the data by removing custom fields
            fields_to_remove = [
                'validating_airline', 'validating_airline_name', 'airline_names',
                'stops', 'origin', 'destination', 'departure_time', 'arrival_time',
                'origin_city', 'origin_country', 'origin_location',
                'destination_city', 'destination_country', 'destination_location',
                'duration', 'formatted_duration', 'travel_class'
            ]
            
            for field in fields_to_remove:
                if field in pricing_data:
                    del pricing_data[field]
        
        # Store in session - store BOTH display data and clean pricing data
        request.session['selected_flight'] = {
            'offer_id': offer_id,
            'price': price,
            'offer_data': pricing_data,  # Clean data for Amadeus API
            'display_data': offer_data,  # Processed data for display
            'selected_at': timezone.now().isoformat(),
            'expires_at': (timezone.now() + timedelta(minutes=30)).isoformat(),
        }
        
        # DEBUG: Log what we're storing
        logger.info("=== SELECT_FLIGHT DEBUG ===")
        logger.info(f"Offer ID: {offer_id}")
        logger.info(f"Display data keys: {list(offer_data.keys())}")
        logger.info(f"Pricing data keys: {list(pricing_data.keys())}")
        logger.info(f"Has itineraries in pricing: {'itineraries' in pricing_data}")
        logger.info(f"Has travelerPricings in pricing: {'travelerPricings' in pricing_data}")
        
        # Also store in database for audit trail
        try:
            existing_offer = FlightOffer.objects.filter(
                offer_id=offer_id, 
                user=request.user
            ).first()
            
            if not existing_offer:
                FlightOffer.objects.create(
                    offer_id=offer_id,
                    user=request.user,
                    offer_data=pricing_data,  # Store clean data for pricing
                    display_data=offer_data,   # Store processed data for display
                    total_price=price,
                    expires_at=timezone.now() + timedelta(minutes=30)
                )
                logger.debug(f"Created new flight offer: {offer_id}")
            else:
                existing_offer.offer_data = pricing_data
                existing_offer.display_data = offer_data
                existing_offer.total_price = price
                existing_offer.expires_at = timezone.now() + timedelta(minutes=30)
                existing_offer.updated_at = timezone.now()
                existing_offer.save()
                logger.debug(f"Updated existing flight offer: {offer_id}")
                
        except Exception as e:
            logger.warning(f"Failed to save/update flight offer: {str(e)}")
        
        messages.success(request, 'Flight selected! Please complete passenger details.')
        return redirect('booking_form')
        
    except Exception as e:
        logger.error(f"Flight selection error: {str(e)}", exc_info=True)
        messages.error(request, 'Error selecting flight. Please try again.')
        return redirect('flight_search_results')


def get_fallback_airports(keyword):
    """Provide fallback airport data if API fails"""
    keyword = keyword.lower()
    all_airports = [
        {'code': 'JFK', 'name': 'John F. Kennedy International Airport', 'city': 'New York'},
        {'code': 'LAX', 'name': 'Los Angeles International Airport', 'city': 'Los Angeles'},
        {'code': 'ORD', 'name': "O'Hare International Airport", 'city': 'Chicago'},
        {'code': 'DFW', 'name': 'Dallas/Fort Worth International Airport', 'city': 'Dallas'},
        {'code': 'ATL', 'name': 'Hartsfield-Jackson Atlanta International Airport', 'city': 'Atlanta'},
        {'code': 'MIA', 'name': 'Miami International Airport', 'city': 'Miami'},
        {'code': 'SFO', 'name': 'San Francisco International Airport', 'city': 'San Francisco'},
        {'code': 'SEA', 'name': 'Seattle-Tacoma International Airport', 'city': 'Seattle'},
        {'code': 'LAS', 'name': 'McCarran International Airport', 'city': 'Las Vegas'},
        {'code': 'MCO', 'name': 'Orlando International Airport', 'city': 'Orlando'},
        {'code': 'LHR', 'name': 'London Heathrow Airport', 'city': 'London'},
        {'code': 'CDG', 'name': 'Charles de Gaulle Airport', 'city': 'Paris'},
        {'code': 'DXB', 'name': 'Dubai International Airport', 'city': 'Dubai'},
        {'code': 'HND', 'name': 'Haneda Airport', 'city': 'Tokyo'},
        {'code': 'SYD', 'name': 'Sydney Kingsford Smith Airport', 'city': 'Sydney'},
    ]
    
    filtered = []
    for airport in all_airports:
        if (keyword in airport['code'].lower() or 
            keyword in airport['name'].lower() or 
            keyword in airport['city'].lower()):
            filtered.append(airport)
    
    return filtered[:10]  # Limit to 10 results

# ==================== FLIGHT PRICING ====================

@login_required
def price_flight(request):
    """Get detailed pricing for selected flight before booking"""
    if request.method != 'POST':
        return redirect('booking_form')
    
    try:
        selected_flight = request.session.get('selected_flight')
        if not selected_flight:
            messages.error(request, 'No flight selected')
            return redirect('flight_search')
        
        # Get traveler details from form
        travelers = parse_travelers_from_request(request)
        
        if not travelers:
            messages.error(request, 'Please provide passenger details')
            return redirect('booking_form')
        
        # **CRITICAL: Get the clean flight offer data for pricing**
        offer_data = selected_flight['offer_data']  # This should be the clean Amadeus data
        
        # DEBUG: Check structure
        logger.info("=== DEBUG BEFORE PRICING ===")
        logger.info(f"Offer data type: {type(offer_data)}")
        logger.info(f"Offer keys: {list(offer_data.keys())}")
        logger.info(f"Has itineraries: {'itineraries' in offer_data}")
        logger.info(f"Has travelerPricings: {'travelerPricings' in offer_data}")
        
        # Call Amadeus pricing API
        priced_offer, error = amadeus_service.price_flights(offer_data, travelers)
        
        if error:
            messages.error(request, f'Pricing failed: {error}')
            return redirect('booking_form')
        
        # Store priced offer in session
        expires_at = timezone.now() + timedelta(minutes=30)
        
        request.session['priced_flight'] = {
            'priced_offer': priced_offer,
            'travelers': travelers,
            'priced_at': timezone.now().isoformat(),
            'expires_at': expires_at.isoformat(),
        }
        
        messages.success(request, 'Flight priced successfully!')
        return redirect('booking_review')
        
    except Exception as e:
        logger.error(f"Flight pricing error: {str(e)}", exc_info=True)
        messages.error(request, 'Error pricing flight. Please try again.')
        return redirect('booking_form')
    
@login_required
def booking_review(request):
    """Display booking review before final confirmation"""
    selected_flight = request.session.get('selected_flight')
    priced_flight = request.session.get('priced_flight')
    
    # DEBUG: Log what's in the session
    logger.debug(f"Selected flight in session: {bool(selected_flight)}")
    logger.debug(f"Priced flight in session: {bool(priced_flight)}")
    
    if priced_flight:
        logger.debug(f"Priced flight keys: {list(priced_flight.keys())}")
        logger.debug(f"Expires at value: {priced_flight.get('expires_at')}")
    
    if not selected_flight or not priced_flight:
        messages.error(request, 'Session expired. Please start over.')
        return redirect('flight_search')
    
    # Check if we have the required data
    if 'priced_offer' not in priced_flight or 'travelers' not in priced_flight:
        messages.error(request, 'Invalid pricing data')
        return redirect('booking_form')
    
    try:
        # Extract price details
        priced_offer = priced_flight['priced_offer']
        
        # Check if priced_offer has the expected structure
        if not priced_offer or 'data' not in priced_offer:
            messages.error(request, 'Invalid pricing data structure')
            return redirect('booking_form')
            
        flight_offers = priced_offer['data'].get('flightOffers', [])
        if not flight_offers:
            messages.error(request, 'No flight offers in pricing response')
            return redirect('booking_form')
            
        flight_offer = flight_offers[0]
        
        # Get traveler count
        travelers = priced_flight['travelers']
        
        # Get flight details for display
        flight_details = selected_flight['offer_data']
        itineraries = flight_details.get('itineraries', [])
        
        if itineraries:
            first_itinerary = itineraries[0]
            segments = first_itinerary.get('segments', [])
            if segments:
                first_segment = segments[0]
                last_segment = segments[-1]
                
                flight_summary = {
                    'origin': first_segment.get('departure', {}).get('iataCode', ''),
                    'destination': last_segment.get('arrival', {}).get('iataCode', ''),
                    'departure': first_segment.get('departure', {}).get('at', ''),
                    'arrival': last_segment.get('arrival', {}).get('at', ''),
                    'duration': first_itinerary.get('duration', ''),
                    'airline': first_segment.get('carrierCode', ''),
                    'stops': len(segments) - 1,

                    'origin_city': first_segment.get('departure', {}).get('city', ''),
                    'origin_country': first_segment.get('departure', {}).get('country', ''),
                    'destination_city': last_segment.get('arrival', {}).get('city', ''),
                    'destination_country': last_segment.get('arrival', {}).get('country', ''),
                }
            else:
                flight_summary = {}
        else:
            flight_summary = {}
        
        # Get expires_at from session, or use default
        expires_at_str = priced_flight.get('expires_at', '')
        if not expires_at_str:
            # Calculate default if missing
            expires_at = timezone.now() + timedelta(minutes=30)
            expires_at_str = expires_at.isoformat()
        
        context = {
            'selected_flight': selected_flight,
            'priced_flight': priced_flight,
            'travelers': travelers,
            'traveler_count': len(travelers),
            'price_details': flight_offer.get('price', {}),
            'flight_summary': flight_summary,
            'expires_at': expires_at_str,  # Now this will always have a value
        }
        
        return render(request, 'core/routes/booking_review.html', context)
        
    except Exception as e:
        logger.error(f"Error loading booking review: {str(e)}", exc_info=True)
        messages.error(request, 'Error loading booking review')
        return redirect('booking_form')

def parse_travelers_from_request(request):
    """Parse traveler details from form data - using CustomUser fields when available"""
    travelers = []
    user = request.user
    
    # Helper function to clean phone numbers - FIXED VERSION
    def clean_phone_number(phone_str):
        if not phone_str:
            return "5555555555"  # Default fallback
        
        # Remove ALL non-digit characters using regex
        cleaned = re.sub(r'\D', '', str(phone_str))
        
        # If empty after cleaning, use default
        if not cleaned:
            return "5555555555"
        
        return cleaned
    
    # Determine how many adults (primary user + additional)
    adults = int(request.POST.get('adults', 1))
    
    # Clean user's phone number - FIXED CALL
    user_phone_cleaned = clean_phone_number(user.phone_number)
    
    # Primary passenger (the user themselves)
    primary_traveler = {
        "id": "1",
        "dateOfBirth": user.date_of_birth.strftime('%Y-%m-%d') if user.date_of_birth else '1980-01-01',
        "name": {
            "firstName": user.first_name or 'User',
            "lastName": user.last_name or 'Name'
        },
        "gender": user.gender or 'MALE',
        "contact": {
            "emailAddress": user.email or f'{user.username}@example.com',
            "phones": [{
                "deviceType": "MOBILE",
                "countryCallingCode": "1",  # Default US
                "number": user_phone_cleaned  # <-- NOW CORRECTLY CLEANED
            }]
        },
        "documents": []
    }
    
    # Add passport if available
    if user.passport_number:
        primary_traveler["documents"] = [{
            "documentType": "PASSPORT",
            "number": user.passport_number or '',
            "expiryDate": user.passport_expiry.strftime('%Y-%m-%d') if user.passport_expiry else '2030-12-31',
            "issuanceCountry": user.nationality or 'US',
            "nationality": user.nationality or 'US',
            "holder": True
        }]
    
    travelers.append(primary_traveler)
    
    # Additional passengers (companions) - starting from index 2
    for i in range(1, adults):  # Start from 1 because 0 is the primary user
        # Clean phone number for additional passenger - FIXED CALL
        additional_phone = request.POST.get(f'adult_{i+1}_phone', '')
        additional_phone_cleaned = clean_phone_number(additional_phone)
        
        traveler = {
            "id": str(i + 1),
            "dateOfBirth": request.POST.get(f'adult_{i+1}_dob', '1980-01-01'),
            "name": {
                "firstName": request.POST.get(f'adult_{i+1}_first_name', ''),
                "lastName": request.POST.get(f'adult_{i+1}_last_name', '')
            },
            "gender": request.POST.get(f'adult_{i+1}_gender', 'MALE'),
            "contact": {
                "emailAddress": request.POST.get(f'adult_{i+1}_email', f'passenger{i+1}@example.com'),
                "phones": [{
                    "deviceType": "MOBILE",
                    "countryCallingCode": "1",
                    "number": additional_phone_cleaned  # <-- NOW CORRECTLY CLEANED
                }]
            },
            "documents": [{
                "documentType": "PASSPORT",
                "number": request.POST.get(f'adult_{i+1}_passport', 'PASS123'),
                "expiryDate": request.POST.get(f'adult_{i+1}_passport_expiry', '2030-12-31'),
                "issuanceCountry": request.POST.get(f'adult_{i+1}_nationality', 'US'),
                "nationality": request.POST.get(f'adult_{i+1}_nationality', 'US'),
                "holder": True
            }]
        }
        travelers.append(traveler)
    
    logger.info(f"Parsed {len(travelers)} travelers")
    # DEBUG: Log phone numbers being sent
    for i, traveler in enumerate(travelers):
        phone = traveler['contact']['phones'][0]['number']
        logger.debug(f"Traveler {i+1} phone: {phone} (length: {len(phone)})")
    
    return travelers
    
# ==================== FLIGHT BOOKING ====================

@login_required
def create_booking(request):
    """Create actual booking with Amadeus API"""
    if request.method != 'POST':
        return redirect('flight_search')
    
    try:
        # Get session data
        selected_flight = request.session.get('selected_flight')
        priced_flight = request.session.get('priced_flight')
        
        if not selected_flight or not priced_flight:
            messages.error(request, 'Session expired. Please select flight again.')
            return redirect('flight_search')
        
        # Get contact information and CLEAN the phone number
        contact_email = request.POST.get('contact_email', request.user.email)
        contact_phone_raw = request.POST.get('contact_phone', '')
        
        # Clean the contact phone number
        contact_phone_cleaned = re.sub(r'\D', '', str(contact_phone_raw))
        if not contact_phone_cleaned:
            contact_phone_cleaned = "5555555555"
        
        contacts = [{
            "emailAddress": contact_email,
            "phones": [{
                "deviceType": "MOBILE",
                "countryCallingCode": "1",
                "number": contact_phone_cleaned  # <-- CLEANED
            }]
        }]
        
        # Create booking with Amadeus
        booking_result, error = amadeus_service.create_booking(
            flight_offer=priced_flight['priced_offer']['data']['flightOffers'][0],
            travelers=priced_flight['travelers'],
            contacts=contacts
        )
        
        if error:
            logger.error(f"Booking failed: {error}")
            messages.error(request, f'Booking failed: {error}')
            return redirect('booking_form')
        
        # Extract booking details
        booking_data = booking_result.get('data', {})
        amadeus_order_id = booking_data.get('id', '')
        
        # FIX: Get PNR safely
        amadeus_pnr = ''
        associated_records = booking_data.get('associatedRecords', [])
        if associated_records:
            amadeus_pnr = associated_records[0].get('reference', '')
        
        # FIX: If PNR is empty, generate a fallback
        if not amadeus_pnr:
            amadeus_pnr = f"TEMP{amadeus_order_id[:8]}" if amadeus_order_id else f"TEMP{int(time.time())}"
            logger.warning(f"PNR not in response, using fallback: {amadeus_pnr}")
        
        # Create reservation in database
        reservation = Reservation.objects.create(
            user=request.user,
            gds_reference=amadeus_order_id,
            airline_pnr=amadeus_pnr,
            status='HOLD',
            expires_at=timezone.now() + timedelta(hours=24),  # Amadeus holds for 24h
            flight_details=booking_data,
            passenger_details=priced_flight['travelers'],
            contact_email=contact_email,
            total_price=selected_flight['price']
        )
        
        # Clear session data
        request.session.pop('selected_flight', None)
        request.session.pop('priced_flight', None)
        
        # Send confirmation email
        send_booking_confirmation(reservation)
        
        messages.success(request, f'Booking confirmed! Your PNR is: {amadeus_pnr}')
        return redirect('booking_confirmation', pnr=amadeus_pnr)
        
    except Exception as e:
        logger.error(f"Booking creation error: {str(e)}", exc_info=True)
        messages.error(request, 'Error creating booking. Please try again.')
        return redirect('booking_form')

def send_booking_confirmation(reservation):  # Fixed: removed self parameter
    """Send booking confirmation email"""
    try:
        subject = f"Flight Booking Confirmation - PNR: {reservation.airline_pnr}"
        
        # Build email content
        flight_details = reservation.flight_details.get('flightOffers', [{}])[0]
        itineraries = flight_details.get('itineraries', [])
        
        context = {
            'reservation': reservation,
            'flight_details': flight_details,
            'itineraries': itineraries,
            'passengers': reservation.passenger_details,
        }
        
        # Send email (implement your email sending logic)
        # send_mail(subject, message, from_email, [reservation.contact_email])
        
        logger.info(f"Booking confirmation sent for PNR: {reservation.airline_pnr}")
        
    except Exception as e:
        logger.error(f"Failed to send confirmation email: {str(e)}")

@login_required
def booking_form(request):
    """Display booking form with selected flight"""
    selected_flight = request.session.get('selected_flight')
    
    if not selected_flight:
        messages.error(request, 'No flight selected')
        return redirect('flight_search')
    
    if request.method == 'POST':
        # Validate adult count vs. adult details
        adults = int(request.POST.get('adults', 1))
        
        # Check if all adult details are provided
        all_adults_valid = True
        missing_fields = []
        
        for i in range(1, adults + 1):
            if i == 1:
                # Primary passenger (user) - check if they have required profile fields
                if not (request.user.first_name and request.user.last_name and request.user.email):
                    all_adults_valid = False
                    missing_fields.append(f"Primary passenger: Please complete your profile details")
            else:
                # Additional adults
                required_fields = [
                    f'adult_{i}_first_name',
                    f'adult_{i}_last_name',
                    f'adult_{i}_dob',
                    f'adult_{i}_gender',
                    f'adult_{i}_email',
                    f'adult_{i}_passport'
                ]
                
                for field in required_fields:
                    if not request.POST.get(field, '').strip():
                        all_adults_valid = False
                        missing_fields.append(f"Adult {i}: {field.replace(f'adult_{i}_', '').replace('_', ' ').title()}")
        
        if not all_adults_valid:
            messages.error(request, f'Missing passenger details: {", ".join(missing_fields[:3])}')
            return redirect('booking_form')
    
    # Check if flight selection is expired
    try:
        expires_at = datetime.fromisoformat(selected_flight.get('expires_at', ''))
        if timezone.now() > expires_at:
            messages.error(request, 'Flight selection expired. Please select again.')
            request.session.pop('selected_flight', None)
            return redirect('flight_search')
    except (ValueError, TypeError):
        messages.error(request, 'Invalid flight selection data')
        request.session.pop('selected_flight', None)
        return redirect('flight_search')
    
    try:
        offer_data = selected_flight['offer_data']
        itineraries = offer_data.get('itineraries', [])
        
        if not itineraries:
            messages.error(request, 'Invalid flight data')
            return redirect('flight_search')
        
        # Extract display information
        first_itinerary = itineraries[0]
        first_segment = first_itinerary.get('segments', [{}])[0]
        last_segment = first_itinerary.get('segments', [{}])[-1]
        
        # Get airline code and name - FIXED: Use proper method
        carrier_code = first_segment.get('carrierCode', '')
        airline_name = ''
        
        # Try to get airline name from multiple sources
        try:
            # First try the batch method with a list
            airline_names = amadeus_service.get_airline_names_batch([carrier_code])
            if airline_names and isinstance(airline_names, list) and len(airline_names) > 0:
                airline_name = airline_names[0]
        except Exception as e:
            logger.warning(f"Batch airline name fetch failed: {str(e)}")
        
        # If batch failed, try alternative methods
        if not airline_name:
            try:
                # Try direct airline lookup
                airline_name = amadeus_service._get_airline_name_fallback(carrier_code)
            except Exception as e:
                logger.warning(f"Fallback airline name fetch failed: {str(e)}")
                airline_name = carrier_code  # Fallback to just showing the code
        
        # Extract travel class
        travel_class = 'ECONOMY'
        try:
            traveler_pricings = offer_data.get('travelerPricings', [])
            if traveler_pricings:
                fare_details = traveler_pricings[0].get('fareDetailsBySegment', [])
                if fare_details:
                    travel_class = fare_details[0].get('cabin', 'ECONOMY')
        except:
            pass
        
        # Format duration
        duration = format_flight_duration(first_itinerary.get('duration', ''))
        
        # Get user information
        user = request.user
        
        # Format dates for display
        departure_at = first_segment.get('departure', {}).get('at', '')
        arrival_at = last_segment.get('arrival', {}).get('at', '')
        
        context = {
            'flight': {
                'id': selected_flight['offer_id'],
                'price': selected_flight['price'],
                'currency': offer_data.get('price', {}).get('currency', 'USD'),
                'origin': first_segment.get('departure', {}).get('iataCode', ''),
                'destination': last_segment.get('arrival', {}).get('iataCode', ''),
                'departure_time': departure_at,
                'arrival_time': arrival_at,
                'duration': duration,
                'airline': airline_name,
                'airline_code': carrier_code,
                'flight_number': f"{carrier_code}{first_segment.get('number', '')}",
                'travel_class': travel_class,
                'stops': len(first_itinerary.get('segments', [])) - 1,
                'last_ticketing_date': offer_data.get('lastTicketingDate', ''),
                'offer_data_json': json.dumps(offer_data),
            },
            'expires_at': expires_at,
            'user_info': {
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'phone': user.phone_number,
                'date_of_birth': user.date_of_birth.strftime('%Y-%m-%d') if user.date_of_birth else '',
                'gender': user.gender,
                'nationality': user.nationality,
                'passport_number': user.passport_number,
                'passport_expiry': user.passport_expiry.strftime('%Y-%m-%d') if user.passport_expiry else '',
            }
        }
        
        # DEBUG: Log what we're sending to template
        logger.debug(f"Flight data for booking form:")
        logger.debug(f"Airline: {airline_name}")
        logger.debug(f"Airline code: {carrier_code}")
        logger.debug(f"Flight number: {carrier_code}{first_segment.get('number', '')}")
        logger.debug(f"Travel class: {travel_class}")
        
        return render(request, 'core/routes/booking_form.html', context)
        
    except Exception as e:
        logger.error(f"Error loading booking form: {str(e)}", exc_info=True)
        messages.error(request, 'Error loading booking form')
        return redirect('flight_search')

# ==================== AJAX ENDPOINTS ====================

@login_required
def search_airports_ajax(request):
    """AJAX endpoint for airport search"""
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)
    
    keyword = request.GET.get('q', '').strip()
    if len(keyword) < 2:
        return JsonResponse({'airports': []})
    
    try:
        airports, error = amadeus_service.search_airports(keyword)
        if error:
            logger.error(f"Airport API error: {error}")
            # Fallback to static data if API fails
            airports = get_fallback_airports(keyword)
        
        return JsonResponse({'airports': airports})
        
    except Exception as e:
        logger.error(f"Airport search error: {str(e)}")
        # Return fallback data on error
        airports = get_fallback_airports(keyword)
        return JsonResponse({'airports': airports})

@login_required
def flight_status_ajax(request):
    """Check flight status"""
    flight_number = request.GET.get('flight_number', '')
    date = request.GET.get('date', '')
    
    if not flight_number or not date:
        return JsonResponse({'error': 'Missing parameters'}, status=400)
    
    try:
        # Implement flight status check using Amadeus API
        # https://developers.amadeus.com/self-service/category/flights/api-doc/flight-status
        pass
        
    except Exception as e:
        logger.error(f"Flight status error: {str(e)}")
        return JsonResponse({'error': 'Status check failed'}, status=500)

# ==================== OTHER VIEWS ====================

@login_required 
def booking_confirmation(request, pnr):
    """Display booking confirmation"""
    try:
        # Check if pnr is not empty
        if not pnr or pnr.strip() == '':
            messages.error(request, 'Invalid booking reference')
            return redirect('my_bookings')
            
        reservation = Reservation.objects.get(airline_pnr=pnr, user=request.user)
        
        # Extract flight details from reservation.flight_details
        flight_details = reservation.flight_details
        flight_offers = flight_details.get('flightOffers', [])
        
        flight = {}  # Initialize empty flight dict for template
        if flight_offers:
            flight_offer = flight_offers[0]
            itineraries = flight_offer.get('itineraries', [])
            
            if itineraries:
                first_itinerary = itineraries[0]
                segments = first_itinerary.get('segments', [])
                
                if segments:
                    first_segment = segments[0]
                    last_segment = segments[-1]
                    
                    # Get airline code and name
                    carrier_code = first_segment.get('carrierCode', '')
                    airline_name = amadeus_service._get_airline_name_fallback(carrier_code)
                    
                    # Format dates for display
                    departure_at = first_segment.get('departure', {}).get('at', '')
                    arrival_at = last_segment.get('arrival', {}).get('at', '')
                    
                    if departure_at:
                        departure_datetime = datetime.fromisoformat(departure_at.replace('Z', '+00:00'))
                    if arrival_at:
                        arrival_datetime = datetime.fromisoformat(arrival_at.replace('Z', '+00:00'))
                    
                    flight = {
                        'origin': first_segment.get('departure', {}).get('iataCode', ''),
                        'destination': last_segment.get('arrival', {}).get('iataCode', ''),
                        'departure_date': departure_datetime if 'departure_datetime' in locals() else None,
                        'departure_time': departure_datetime if 'departure_datetime' in locals() else None,
                        'arrival_date': arrival_datetime if 'arrival_datetime' in locals() else None,
                        'arrival_time': arrival_datetime if 'arrival_datetime' in locals() else None,
                        'airline_code': carrier_code,
                        'airline_name': airline_name,
                        'flight_number': f"{carrier_code}{first_segment.get('number', '')}",
                        'duration': first_itinerary.get('duration', ''),
                        'stops': len(segments) - 1,
                        'price': flight_offer.get('price', {}),
                    }
        
        # Get price from flight or reservation
        total_price = flight.get('price', {}).get('total', reservation.total_price) if flight else reservation.total_price
        
        # Check if reservation has ticketing_deadline field, otherwise calculate it
        ticketing_deadline = getattr(reservation, 'ticketing_deadline', None)
        if not ticketing_deadline and flight_offers:
            last_ticketing_date = flight_offers[0].get('lastTicketingDate', '')
            if last_ticketing_date:
                ticketing_deadline = datetime.fromisoformat(last_ticketing_date.replace('Z', '+00:00'))
        
        context = {
            'reservation': reservation,
            'flight': flight,
            'total_price': total_price,
            'ticketing_deadline': ticketing_deadline,
            'flight_details': flight_details,
            'passengers': reservation.passenger_details,
            'pnr': pnr,
        }
        
        return render(request, 'core/routes/confirmation.html', context)
        
    except Reservation.DoesNotExist:
        messages.error(request, 'Booking not found')
        return redirect('my_bookings')

@login_required
def my_bookings(request):
    """Display user's bookings with real data"""
    status_filter = request.GET.get('status', 'all')
    
    # Get user's real bookings
    bookings = Reservation.objects.filter(user=request.user)
    
    if status_filter != 'all':
        bookings = bookings.filter(status=status_filter)
    
    # Order by creation date (newest first)
    bookings = bookings.order_by('-created_at')
    
    # ========== FIX: PREPARE FLIGHT DATA FOR TEMPLATE ==========
    for booking in bookings:
        # Add flight_offer to each booking object for template compatibility
        # Check if flight_details exists and has the expected structure
        if hasattr(booking, 'flight_details') and booking.flight_details:
            try:
                # Ensure flight_details is a dict, not string
                if isinstance(booking.flight_details, str):
                    import json
                    flight_data = json.loads(booking.flight_details)
                else:
                    flight_data = booking.flight_details
                
                # Check if it has flightOffers
                if isinstance(flight_data, dict) and 'flightOffers' in flight_data:
                    flight_offers = flight_data.get('flightOffers', [])
                    if flight_offers:
                        # Get first flight offer
                        flight_offer = flight_offers[0]
                        
                        # Add flight_offer attribute to booking for template
                        booking.flight_offer = flight_offer
                        
                        # Extract itineraries for easy access
                        itineraries = flight_offer.get('itineraries', [])
                        booking.itineraries = itineraries
                        
                        # Extract price
                        price_info = flight_offer.get('price', {})
                        booking.price_info = price_info
                        
            except Exception as e:
                logger.error(f"Error processing flight details for booking {booking.pk}: {e}")
                # Set empty data on error
                booking.flight_offer = {}
                booking.itineraries = []
                booking.price_info = {}
        else:
            # Set empty data if no flight_details
            booking.flight_offer = {}
            booking.itineraries = []
            booking.price_info = {}
    # ========== END FIX ==========
    
    # Pagination
    paginator = Paginator(bookings, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Statistics
    stats = {
        'active_holds': bookings.filter(status='HOLD').count(),
        'confirmed': bookings.filter(status='CONFIRMED').count(),
        'ticketed': bookings.filter(status='TICKETED').count(),
        'expired': bookings.filter(status='EXPIRED').count(),
        'cancelled': bookings.filter(status='CANCELLED').count(),
        'total_bookings': bookings.count(),
    }
    
    context = {
        'bookings': page_obj,
        'page_obj': page_obj,
        'current_status': status_filter,
        **stats
    }
    
    return render(request, 'core/routes/my_bookings.html', context)

# ==================== UTILITY FUNCTIONS ====================

def validate_search_params(get_params):
    """Validate and normalize search parameters"""
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
            'max_results': int(get_params.get('max_results', 50)),
            'trip_type': get_params.get('trip_type', 'oneway'),
            # 'currency': get_params.get('currency', 'USD').upper(),
            # 'non_stop': get_params.get('nonstop') == 'true',
        }
        
        # Basic validation
        if len(params['origin']) != 3 or len(params['destination']) != 3:
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
        
    except (ValueError, KeyError):
        return None

def format_duration(duration_str):  # Fixed: removed self parameter
    """Format ISO duration string"""
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

def extract_travel_class(offer_data):  # Fixed: removed self parameter
    """Extract travel class from offer"""
    try:
        traveler_pricings = offer_data.get('travelerPricings', [])
        if traveler_pricings:
            fare_details = traveler_pricings[0].get('fareDetailsBySegment', [])
            if fare_details:
                return fare_details[0].get('cabin', 'ECONOMY')
    except:
        pass
    return 'ECONOMY'

def format_flight_duration(iso_duration):
    """Format ISO 8601 duration to readable format"""
    if not iso_duration:
        return ""
    
    # Remove PT prefix
    duration = str(iso_duration).replace('PT', '')
    
    hours = ""
    minutes = ""
    
    if 'H' in duration:
        parts = duration.split('H')
        hours = f"{parts[0]}h "
        duration = parts[1] if len(parts) > 1 else ""
    
    if 'M' in duration:
        parts = duration.split('M')
        minutes = f"{parts[0]}m"
    
    return f"{hours}{minutes}".strip()

@login_required
def view_booking(request, pnr):
    """View details of a specific booking"""
    try:
        booking = Reservation.objects.get(airline_pnr=pnr, user=request.user)
        
        # Process flight details for the template
        flight_details = {}
        if booking.flight_details:
            try:
                # Parse flight details
                if isinstance(booking.flight_details, str):
                    flight_data = json.loads(booking.flight_details)
                else:
                    flight_data = booking.flight_details
                
                flight_offers = flight_data.get('flightOffers', [])
                if flight_offers:
                    flight_offer = flight_offers[0]
                    
                    # Extract flight information
                    itineraries = flight_offer.get('itineraries', [])
                    if itineraries:
                        first_itinerary = itineraries[0]
                        segments = first_itinerary.get('segments', [])
                        
                        if segments:
                            first_segment = segments[0]
                            last_segment = segments[-1]
                            
                            # Get airline name
                            carrier_code = first_segment.get('carrierCode', '')
                            airline_name = amadeus_service._get_airline_name_fallback(carrier_code)
                            
                            # Format dates
                            departure_at = first_segment.get('departure', {}).get('at', '')
                            arrival_at = last_segment.get('arrival', {}).get('at', '')
                            
                            departure_datetime = None
                            arrival_datetime = None
                            
                            if departure_at:
                                try:
                                    departure_datetime = datetime.fromisoformat(departure_at.replace('Z', '+00:00'))
                                except:
                                    departure_datetime = None
                            
                            if arrival_at:
                                try:
                                    arrival_datetime = datetime.fromisoformat(arrival_at.replace('Z', '+00:00'))
                                except:
                                    arrival_datetime = None
                            
                            flight_details = {
                                'origin': first_segment.get('departure', {}).get('iataCode', ''),
                                'destination': last_segment.get('arrival', {}).get('iataCode', ''),
                                'departure_date': departure_datetime,
                                'departure_time': departure_datetime,
                                'arrival_date': arrival_datetime,
                                'arrival_time': arrival_datetime,
                                'airline_code': carrier_code,
                                'airline_name': airline_name,
                                'flight_number': f"{carrier_code}{first_segment.get('number', '')}",
                                'duration': first_itinerary.get('duration', ''),
                                'stops': len(segments) - 1,
                                'price': flight_offer.get('price', {}),
                            }
            except Exception as e:
                logger.error(f"Error parsing flight details for view_booking: {e}")
        
        context = {
            'booking': booking,
            'flight': flight_details,
            'passengers': booking.passenger_details,
            'flight_data': booking.flight_details,
        }
        
        return render(request, 'core/routes/booking_details.html', context)
        
    except Reservation.DoesNotExist:
        messages.error(request, 'Booking not found')
        return redirect('my_bookings')
    
@login_required
def api_booking_details(request, pnr):
    """API endpoint for booking details (used by AJAX modal)"""
    try:
        booking = Reservation.objects.get(airline_pnr=pnr, user=request.user)
        
        # Prepare response data
        data = {
            'pnr': booking.airline_pnr,
            'status': booking.status,
            'created_at': booking.created_at.isoformat(),
            'expires_at': booking.expires_at.isoformat(),
            'contact_email': booking.contact_email,
            'total_price': str(booking.total_price),
        }
        
        # Add passenger details
        if booking.passenger_details:
            data['passengers'] = booking.passenger_details
        else:
            data['passengers'] = []
        
        # Add flight itinerary details
        if booking.flight_details:
            try:
                # Parse flight details
                if isinstance(booking.flight_details, str):
                    import json
                    flight_data = json.loads(booking.flight_details)
                else:
                    flight_data = booking.flight_details
                
                # Extract itineraries
                flight_offers = flight_data.get('flightOffers', [])
                if flight_offers:
                    flight_offer = flight_offers[0]
                    itineraries = flight_offer.get('itineraries', [])
                    if itineraries:
                        data['itinerary'] = itineraries[0]
                        
                        # Add formatted segments
                        segments = itineraries[0].get('segments', [])
                        for segment in segments:
                            # Format times for display
                            departure_at = segment.get('departure', {}).get('at', '')
                            arrival_at = segment.get('arrival', {}).get('at', '')
                            
                            if departure_at:
                                try:
                                    from datetime import datetime
                                    dt = datetime.fromisoformat(departure_at.replace('Z', '+00:00'))
                                    segment['departure']['formatted_time'] = dt.strftime('%H:%M')
                                    segment['departure']['formatted_date'] = dt.strftime('%b %d, %Y')
                                except:
                                    segment['departure']['formatted_time'] = departure_at[11:16]
                            
                            if arrival_at:
                                try:
                                    from datetime import datetime
                                    dt = datetime.fromisoformat(arrival_at.replace('Z', '+00:00'))
                                    segment['arrival']['formatted_time'] = dt.strftime('%H:%M')
                                    segment['arrival']['formatted_date'] = dt.strftime('%b %d, %Y')
                                except:
                                    segment['arrival']['formatted_time'] = arrival_at[11:16]
                        
                        data['segments'] = segments
            except Exception as e:
                logger.error(f"Error parsing flight details: {e}")
                data['itinerary'] = {}
                data['segments'] = []
        else:
            data['itinerary'] = {}
            data['segments'] = []
        
        return JsonResponse(data)
        
    except Reservation.DoesNotExist:
        return JsonResponse({'error': 'Booking not found'}, status=404)
    except Exception as e:
        logger.error(f"Error in API booking details: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@login_required
def download_itinerary(request, pnr):
    """Download itinerary PDF"""
    try:
        booking = Reservation.objects.get(airline_pnr=pnr, user=request.user)
        
        # Extract flight details
        flight_details = {}
        passengers = booking.passenger_details or []
        
        if booking.flight_details:
            try:
                # Parse flight details
                if isinstance(booking.flight_details, str):
                    flight_data = json.loads(booking.flight_details)
                else:
                    flight_data = booking.flight_details
                
                flight_offers = flight_data.get('flightOffers', [])
                if flight_offers:
                    flight_offer = flight_offers[0]
                    itineraries = flight_offer.get('itineraries', [])
                    
                    if itineraries:
                        first_itinerary = itineraries[0]
                        segments = first_itinerary.get('segments', [])
                        
                        if segments:
                            first_segment = segments[0]
                            last_segment = segments[-1]
                            
                            # Get airline name
                            carrier_code = first_segment.get('carrierCode', '')
                            try:
                                airline_name = amadeus_service.get_airline_names_batch([carrier_code])
                                if isinstance(airline_name, list) and airline_name:
                                    airline_name = airline_name[0]
                            except:
                                airline_name = carrier_code
                            
                            flight_details = {
                                'origin': first_segment.get('departure', {}).get('iataCode', ''),
                                'destination': last_segment.get('arrival', {}).get('iataCode', ''),
                                'airline_name': airline_name,
                                'flight_number': f"{carrier_code}{first_segment.get('number', '')}",
                                'departure': first_segment.get('departure', {}).get('at', ''),
                                'arrival': last_segment.get('arrival', {}).get('at', ''),
                                'duration': first_itinerary.get('duration', ''),
                                'stops': len(segments) - 1,
                            }
            except Exception as e:
                logger.error(f"Error parsing flight details for PDF: {e}")
        
        # CHOOSE YOUR PDF GENERATOR:
        # Option 1: Use ReportLab (better for complex layouts)
        # Option 2: Use WeasyPrint (better for HTML/CSS layouts)
        
        # Option 1: ReportLab
        try:
            pdf_buffer = ReportLabPDFGenerator.generate_itinerary(
                booking=booking,
                flight_details=flight_details,
                passengers=passengers
            )
            pdf_content = pdf_buffer.getvalue()
            pdf_buffer.close()
        except Exception as e:
            logger.error(f"ReportLab failed, trying WeasyPrint: {e}")
            # Option 2: Fallback to WeasyPrint
            try:
                pdf_buffer = WeasyPrintPDFGenerator.generate_itinerary(
                    booking=booking,
                    flight_details=flight_details,
                    passengers=passengers
                )
                pdf_content = pdf_buffer.getvalue()
                pdf_buffer.close()
            except Exception as e2:
                logger.error(f"WeasyPrint also failed: {e2}")
                messages.error(request, 'PDF generation failed. Please try again.')
                return redirect('view_booking', pnr=pnr)
        
        # Create HTTP response
        filename = f"itinerary_{booking.airline_pnr}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        response = HttpResponse(pdf_content, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Reservation.DoesNotExist:
        messages.error(request, 'Booking not found')
        return redirect('my_bookings')
    except Exception as e:
        logger.error(f"Error generating itinerary PDF: {e}")
        messages.error(request, 'Failed to generate itinerary. Please try again.')
        return redirect('view_booking', pnr=pnr)


@login_required
def download_official_itinerary(request, pnr):
    """Download official Amadeus-standard itinerary receipt"""
    try:
        booking = Reservation.objects.get(airline_pnr=pnr, user=request.user)
        
        # Extract flight details
        flight_details = {}
        passengers = booking.passenger_details or []
        
        if booking.flight_details:
            try:
                if isinstance(booking.flight_details, str):
                    flight_data = json.loads(booking.flight_details)
                else:
                    flight_data = booking.flight_details
                
                flight_offers = flight_data.get('flightOffers', [])
                if flight_offers:
                    flight_offer = flight_offers[0]
                    
                    # Get airline names
                    airline_codes = set()
                    itineraries = flight_offer.get('itineraries', [])
                    for itinerary in itineraries:
                        for segment in itinerary.get('segments', []):
                            airline_codes.add(segment.get('carrierCode', ''))
                    
                    airline_names = []
                    for code in airline_codes:
                        try:
                            # Try to get airline name from Amadeus service
                            if hasattr(amadeus_service, 'get_airline_names_batch'):
                                name = amadeus_service.get_airline_names_batch([code])
                                if isinstance(name, list) and name:
                                    airline_names.append(name[0])
                            else:
                                airline_names.append(code)
                        except:
                            airline_names.append(code)
                    
                    flight_details = {
                        'itineraries': itineraries,
                        'price': flight_offer.get('price', {}),
                        'travelerPricings': flight_offer.get('travelerPricings', []),
                        'airline_names': airline_names
                    }
            except Exception as e:
                logger.error(f"Error parsing flight details for official itinerary: {e}")
        
        # Agency information (customize with your agency details)
        agency_info = {
            'name': 'FlightReserve Travel Agency',
            'iata_number': '12345678',  # Replace with your IATA number
            'address': '123 Travel Street, New York, NY 10001, USA',
            'phone': '+1 (800) FLY-RESERVE',
            'email': 'support@flightreserve.com'
        }
        
        # Generate official Amadeus itinerary
        pdf_buffer = AmadeusOfficialItineraryGenerator.generate_official_itinerary(
            booking=booking,
            flight_details=flight_details,
            passengers=passengers,
            agency_info=agency_info
        )
        
        pdf_content = pdf_buffer.getvalue()
        pdf_buffer.close()
        
        # Create HTTP response
        filename = f"Official_Itinerary_{booking.airline_pnr}.pdf"
        
        response = HttpResponse(pdf_content, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Reservation.DoesNotExist:
        messages.error(request, 'Booking not found')
        return redirect('my_bookings')
    except Exception as e:
        logger.error(f"Error generating official itinerary PDF: {e}")
        messages.error(request, 'Failed to generate official itinerary. Please try again.')
        return redirect('view_booking', pnr=pnr)

# Add to your views.py
@login_required
def debug_pricing_data(request):
    """Debug view to see pricing data"""
    selected_flight = request.session.get('selected_flight')
    if not selected_flight:
        return HttpResponse("No flight selected")
    
    # Parse travelers from request or use dummy data
    travelers = []
    if request.method == 'POST':
        travelers = parse_travelers_from_request(request)
    
    if not travelers:
        # Create dummy traveler for debugging
        travelers = [{
            "id": "1",
            "dateOfBirth": "1980-01-01",
            "name": {
                "firstName": "John",
                "lastName": "Doe"
            },
            "gender": "MALE",
            "contact": {
                "emailAddress": "john@example.com",
                "phones": [{
                    "deviceType": "MOBILE",
                    "countryCallingCode": "1",
                    "number": "5551234567"
                }]
            }
        }]
    
    # Get the flight offer
    flight_offer = selected_flight['offer_data']
    if isinstance(flight_offer, str):
        import json
        flight_offer = json.loads(flight_offer)
    
    # Create payload
    payload = {
        "data": {
            "type": "flight-offers-pricing",
            "flightOffers": [flight_offer],
            "travelers": travelers
        }
    }
    
    # Remove any extra fields we added
    fields_to_remove = ['validating_airline', 'validating_airline_name', 
                       'airline_names', 'stops', 'origin', 'destination',
                       'departure_time', 'arrival_time', 'duration',
                       'formatted_duration', 'travel_class']
    
    for field in fields_to_remove:
        if field in payload["data"]["flightOffers"][0]:
            del payload["data"]["flightOffers"][0][field]
    
    response = HttpResponse(json.dumps(payload, indent=2), content_type='application/json')
    response['Content-Disposition'] = 'attachment; filename="pricing_debug.json"'
    return response


# In views.py
@login_required
def debug_flight_offer(request):
    """Debug view to see the flight offer structure"""
    selected_flight = request.session.get('selected_flight')
    if not selected_flight:
        return HttpResponse("No flight selected")
    
    flight_offer = selected_flight['offer_data']
    
    # Convert to pretty JSON
    import json
    pretty_json = json.dumps(flight_offer, indent=2)
    
    # Check for travelerPricings
    has_traveler_pricings = 'travelerPricings' in flight_offer
    traveler_pricings_count = len(flight_offer.get('travelerPricings', []))
    
    html = f"""
    <html>
    <head><title>Flight Offer Debug</title></head>
    <body>
        <h1>Flight Offer Structure</h1>
        <p><strong>Has travelerPricings:</strong> {has_traveler_pricings}</p>
        <p><strong>Number of travelerPricings:</strong> {traveler_pricings_count}</p>
        <h2>Full JSON:</h2>
        <pre style="background: #f0f0f0; padding: 10px; overflow: auto; max-height: 600px;">
        {pretty_json}
        </pre>
    </body>
    </html>
    """
    
    return HttpResponse(html)

# In views.py
import json
from django.http import HttpResponse

@login_required
def debug_pricing_payload(request):
    """Debug view to see the exact pricing payload"""
    selected_flight = request.session.get('selected_flight')
    if not selected_flight:
        return HttpResponse("No flight selected")
    
    # Create dummy traveler
    travelers = [{
        "id": "1",
        "dateOfBirth": "1980-01-01",
        "name": {
            "firstName": "John",
            "lastName": "Doe"
        },
        "gender": "MALE",
        "contact": {
            "emailAddress": "john@example.com",
            "phones": [{
                "deviceType": "MOBILE",
                "countryCallingCode": "1",
                "number": "5551234567"
            }]
        }
    }]
    
    flight_offer = selected_flight['offer_data']
    
    # Create clean flight offer
    clean_flight_offer = {}
    original_fields = [
        'type', 'id', 'source', 'instantTicketingRequired', 
        'nonHomogeneous', 'oneWay', 'isUpsellOffer', 
        'lastTicketingDate', 'lastTicketingDateTime', 
        'numberOfBookableSeats', 'itineraries', 'price', 
        'pricingOptions', 'validatingAirlineCodes', 'travelerPricings'
    ]
    
    for field in original_fields:
        if field in flight_offer:
            clean_flight_offer[field] = flight_offer[field]
    
    clean_flight_offer['type'] = 'flight-offer'
    
    # Create payload
    payload = {
        "data": {
            "type": "flight-offers-pricing",
            "flightOffers": [clean_flight_offer],
            "travelers": travelers
        }
    }
    
    # Remove travelerPricings
    if 'travelerPricings' in clean_flight_offer:
        del clean_flight_offer['travelerPricings']
    
    response = HttpResponse(json.dumps(payload, indent=2), content_type='application/json')
    response['Content-Disposition'] = 'attachment; filename="pricing_payload.json"'
    return response

@login_required
def debug_flight_offer_data(request):
    """Debug view to inspect flight offer data"""
    selected_flight = request.session.get('selected_flight')
    
    if not selected_flight:
        return HttpResponse("No flight selected in session")
    
    offer_data = selected_flight.get('offer_data', {})
    
    # Check if it's a string (JSON) or dict
    if isinstance(offer_data, str):
        try:
            import json
            offer_data = json.loads(offer_data)
        except:
            return HttpResponse(f"Invalid JSON in offer_data: {offer_data[:500]}")
    
    # Check critical fields
    html = f"""
    <html>
    <head><title>Flight Offer Debug</title></head>
    <body>
        <h1>Flight Offer Debug</h1>
        <p><strong>Type:</strong> {offer_data.get('type', 'MISSING')}</p>
        <p><strong>ID:</strong> {offer_data.get('id', 'MISSING')}</p>
        <p><strong>Has travelerPricings:</strong> {'travelerPricings' in offer_data}</p>
        <p><strong>Has itineraries:</strong> {'itineraries' in offer_data}</p>
        
        <h2>Itineraries:</h2>
    """
    
    if 'itineraries' in offer_data:
        itineraries = offer_data['itineraries']
        html += f"<p>Number of itineraries: {len(itineraries)}</p>"
        
        for i, itinerary in enumerate(itineraries):
            html += f"<h3>Itinerary {i+1}:</h3>"
            html += f"<p>Duration: {itinerary.get('duration', 'MISSING')}</p>"
            segments = itinerary.get('segments', [])
            html += f"<p>Number of segments: {len(segments)}</p>"
            
            for j, segment in enumerate(segments):
                html += f"<h4>Segment {j+1}:</h4>"
                html += f"<pre>"
                html += f"Departure: {segment.get('departure', {}).get('iataCode', 'MISSING')} at {segment.get('departure', {}).get('at', 'MISSING')}<br>"
                html += f"Arrival: {segment.get('arrival', {}).get('iataCode', 'MISSING')} at {segment.get('arrival', {}).get('at', 'MISSING')}<br>"
                html += f"Carrier: {segment.get('carrierCode', 'MISSING')}<br>"
                html += f"Number: {segment.get('number', 'MISSING')}<br>"
                html += f"</pre>"
    
    html += f"""
        <h2>Traveler Pricings:</h2>
        <p>Number of travelerPricings: {len(offer_data.get('travelerPricings', []))}</p>
    """
    
    if 'travelerPricings' in offer_data:
        for i, tp in enumerate(offer_data['travelerPricings']):
            html += f"<h3>Traveler Pricing {i+1}:</h3>"
            html += f"<p>Traveler ID: {tp.get('travelerId', 'MISSING')}</p>"
            html += f"<p>Fare details: {len(tp.get('fareDetailsBySegment', []))}</p>"
            html += f"<p>Price: {tp.get('price', {}).get('total', 'MISSING')}</p>"
    
    html += f"""
        <h2>Full JSON (first 2000 chars):</h2>
        <pre style="background: #f0f0f0; padding: 10px; overflow: auto; max-height: 600px;">
        {json.dumps(offer_data, indent=2)[:2000]}
        </pre>
    </body>
    </html>
    """
    
    return HttpResponse(html)

# @login_required
# def test_amadeus_pricing_directly(request):
#     """Test Amadeus pricing API directly with a known working payload"""
    
#     # Example of a working Amadeus pricing payload (from their documentation)
#     test_payload = {
#         "data": {
#             "type": "flight-offers-pricing",
#             "flightOffers": [
#                 {
#                     "type": "flight-offer",
#                     "id": "1",
#                     "source": "GDS",
#                     "instantTicketingRequired": False,
#                     "nonHomogeneous": False,
#                     "oneWay": False,
#                     "lastTicketingDate": "2026-09-28",
#                     "lastTicketingDateTime": "2026-09-28",
#                     "numberOfBookableSeats": 9,
#                     "itineraries": [
#                         {
#                             "duration": "PT5H40M",
#                             "segments": [
#                                 {
#                                     "departure": {
#                                         "iataCode": "JFK",
#                                         "at": "2026-09-28T06:05:00"
#                                     },
#                                     "arrival": {
#                                         "iataCode": "LAX",
#                                         "at": "2026-09-28T11:30:00"
#                                     },
#                                     "carrierCode": "AA",
#                                     "number": "100",
#                                     "aircraft": {
#                                         "code": "321"
#                                     },
#                                     "operating": {
#                                         "carrierCode": "AA"
#                                     },
#                                     "duration": "PT5H40M",
#                                     "id": "1",
#                                     "numberOfStops": 0,
#                                     "blacklistedInEU": False
#                                 }
#                             ]
#                         }
#                     ],
#                     "price": {
#                         "currency": "EUR",
#                         "total": "659.06",
#                         "base": "148.00",
#                         "fees": [
#                             {
#                                 "amount": "0.00",
#                                 "type": "SUPPLIER"
#                             },
#                             {
#                                 "amount": "0.00",
#                                 "type": "TICKETING"
#                             }
#                         ],
#                         "grandTotal": "659.06"
#                     },
#                     "pricingOptions": {
#                         "fareType": ["PUBLISHED"],
#                         "includedCheckedBagsOnly": True
#                     },
#                     "validatingAirlineCodes": ["AA"],
#                     "travelerPricings": [
#                         {
#                             "travelerId": "1",
#                             "fareOption": "STANDARD",
#                             "travelerType": "ADULT",
#                             "price": {
#                                 "currency": "EUR",
#                                 "total": "659.06",
#                                 "base": "148.00"
#                             },
#                             "fareDetailsBySegment": [
#                                 {
#                                     "segmentId": "1",
#                                     "cabin": "ECONOMY",
#                                     "fareBasis": "K03LGTE0",
#                                     "class": "K",
#                                     "includedCheckedBags": {
#                                         "quantity": 1
#                                     }
#                                 }
#                             ]
#                         }
#                     ]
#                 }
#             ],
#             "travelers": [
#                 {
#                     "id": "1",
#                     "dateOfBirth": "1980-01-01",
#                     "name": {
#                         "firstName": "John",
#                         "lastName": "Doe"
#                     },
#                     "gender": "MALE",
#                     "contact": {
#                         "emailAddress": "john.doe@example.com",
#                         "phones": [
#                             {
#                                 "deviceType": "MOBILE",
#                                 "countryCallingCode": "1",
#                                 "number": "5551234567"
#                             }
#                         ]
#                     }
#                 }
#             ]
#         }
#     }
    
#     # Test the API directly
#     token = amadeus_service._get_access_token()
    
#     if not token:
#         return HttpResponse("No access token")
    
#     headers = {
#         'Authorization': f'Bearer {token}',
#         'Content-Type': 'application/vnd.amadeus+json'
#     }
    
#     try:
#         response = requests.post(
#             "https://test.api.amadeus.com/v1/shopping/flight-offers/pricing",
#             headers=headers,
#             json=test_payload,
#             timeout=30
#         )
        
#         result = {
#             "status_code": response.status_code,
#             "response": response.json() if response.status_code == 200 else response.text[:500]
#         }
        
#         return JsonResponse(result)
#     except Exception as e:
#         return JsonResponse({"error": str(e)})

# @login_required
# def view_raw_amadeus_data(request):
#     """View the raw Amadeus data stored in session"""
#     selected_flight = request.session.get('selected_flight')
    
#     if not selected_flight:
#         return HttpResponse("No flight selected")
    
#     offer_data = selected_flight.get('offer_data', {})
    
#     # Create a detailed analysis
#     html = f"""
#     <html>
#     <head><title>Raw Amadeus Data Analysis</title>
#     <style>
#         table {{ border-collapse: collapse; width: 100%; }}
#         th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
#         th {{ background-color: #f2f2f2; }}
#         .missing {{ color: red; font-weight: bold; }}
#         .present {{ color: green; font-weight: bold; }}
#     </style>
#     </head>
#     <body>
#         <h1>Raw Amadeus Data Analysis</h1>
#     """
    
#     # Check required fields
#     required_fields = ['type', 'id', 'itineraries', 'travelerPricings', 'price']
#     for field in required_fields:
#         status = "present" if field in offer_data else "missing"
#         html += f'<p><span class="{status}">{field}</span>: {status.upper()}</p>'
    
#     # Analyze itineraries
#     if 'itineraries' in offer_data:
#         html += f'<h2>Itineraries: {len(offer_data["itineraries"])}</h2>'
#         for i, itinerary in enumerate(offer_data['itineraries']):
#             html += f'<h3>Itinerary {i+1}</h3>'
#             html += f'<p>Duration: {itinerary.get("duration", "MISSING")}</p>'
#             segments = itinerary.get('segments', [])
#             html += f'<p>Segments: {len(segments)}</p>'
            
#             for j, segment in enumerate(segments):
#                 html += f'<h4>Segment {j+1}</h4>'
#                 html += f'<table>'
#                 html += f'<tr><th>Field</th><th>Value</th></tr>'
                
#                 for key in ['id', 'carrierCode', 'number', 'duration']:
#                     value = segment.get(key, 'MISSING')
#                     status = "present" if value != 'MISSING' else "missing"
#                     html += f'<tr><td>{key}</td><td class="{status}">{value}</td></tr>'
                
#                 if 'departure' in segment:
#                     dep = segment['departure']
#                     html += f'<tr><td>departure.iataCode</td><td>{dep.get("iataCode", "MISSING")}</td></tr>'
#                     html += f'<tr><td>departure.at</td><td>{dep.get("at", "MISSING")}</td></tr>'
                
#                 if 'arrival' in segment:
#                     arr = segment['arrival']
#                     html += f'<tr><td>arrival.iataCode</td><td>{arr.get("iataCode", "MISSING")}</td></tr>'
#                     html += f'<tr><td>arrival.at</td><td>{arr.get("at", "MISSING")}</td></tr>'
                
#                 html += f'</table>'
    
#     # Analyze travelerPricings
#     if 'travelerPricings' in offer_data:
#         html += f'<h2>Traveler Pricings: {len(offer_data["travelerPricings"])}</h2>'
#         for i, tp in enumerate(offer_data['travelerPricings']):
#             html += f'<h3>Traveler Pricing {i+1}</h3>'
#             html += f'<p>Traveler ID: {tp.get("travelerId", "MISSING")}</p>'
            
#             fare_details = tp.get('fareDetailsBySegment', [])
#             html += f'<p>Fare Details: {len(fare_details)}</p>'
            
#             for j, fd in enumerate(fare_details):
#                 html += f'<p>Segment {j+1} ID: {fd.get("segmentId", "MISSING")}</p>'
    
#     # Check segment ID mapping
#     html += f'<h2>Segment ID Mapping Check</h2>'
    
#     segment_ids_from_itineraries = []
#     if 'itineraries' in offer_data:
#         for itinerary in offer_data['itineraries']:
#             for segment in itinerary.get('segments', []):
#                 seg_id = segment.get('id')
#                 if seg_id:
#                     segment_ids_from_itineraries.append(seg_id)
    
#     segment_ids_from_pricings = []
#     if 'travelerPricings' in offer_data:
#         for tp in offer_data['travelerPricings']:
#             for fd in tp.get('fareDetailsBySegment', []):
#                 seg_id = fd.get('segmentId')
#                 if seg_id:
#                     segment_ids_from_pricings.append(seg_id)
    
#     html += f'<p>Segment IDs in itineraries: {", ".join(segment_ids_from_itineraries)}</p>'
#     html += f'<p>Segment IDs in travelerPricings: {", ".join(segment_ids_from_pricings)}</p>'
    
#     # Check for mismatches
#     mismatches = []
#     for seg_id in segment_ids_from_pricings:
#         if seg_id not in segment_ids_from_itineraries:
#             mismatches.append(seg_id)
    
#     if mismatches:
#         html += f'<p class="missing">ERROR: Segment IDs in travelerPricings but not in itineraries: {", ".join(mismatches)}</p>'
#     else:
#         html += f'<p class="present">OK: All segment IDs match</p>'
    
#     # Show full JSON
#     html += f'<h2>Full JSON</h2>'
#     html += f'<pre style="background: #f0f0f0; padding: 10px; overflow: auto; max-height: 800px;">'
#     html += json.dumps(offer_data, indent=2)
#     html += f'</pre>'
    
#     html += f'</body></html>'
    
#     return HttpResponse(html)




