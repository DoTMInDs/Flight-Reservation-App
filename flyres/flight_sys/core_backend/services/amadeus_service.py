# flight_sys/core_backend/services/amadeus_service.py
import requests
import json
import logging
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
import time

# ========== ADD THESE ERROR CLASSES ==========
class FlightBookingError(Exception):
    """Base exception for flight booking errors"""
    pass

class NoFlightsError(FlightBookingError):
    """No flights available for selected dates"""
    pass

class FareRuleError(FlightBookingError):
    """Fare rules not met for selected dates"""
    pass

class MinimumStayError(FlightBookingError):
    """Minimum stay requirement not met"""
    pass

class SoldOutError(FlightBookingError):
    """Flights sold out for selected date"""
    pass

class ScheduleGapError(FlightBookingError):
    """No valid itinerary due to schedule gaps"""
    pass
# ========== END ERROR CLASSES ==========

logger = logging.getLogger(__name__)

class AmadeusService:
    """Amadeus API service"""
    
    def __init__(self):
        self.base_url = "https://test.api.amadeus.com"  # Sandbox for testing
        self.timeout = 30
        self.max_retries = 3
        
    def _get_access_token(self):
        """Get Amadeus access token with debugging"""
        cache_key = "amadeus_access_token"
        cached_token = cache.get(cache_key)
        
        if cached_token:
            logger.debug(f"Using cached token: {cached_token[:20]}...")
            return cached_token
        
        try:
            logger.debug(f"Fetching new token with key: {settings.AMADEUS_API_KEY[:10]}...")
            
            response = requests.post(
                f"{self.base_url}/v1/security/oauth2/token",
                data={
                    'grant_type': 'client_credentials',
                    'client_id': settings.AMADEUS_API_KEY,
                    'client_secret': settings.AMADEUS_API_SECRET
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=10
            )
            
            logger.debug(f"Token response status: {response.status_code}")
            logger.debug(f"Token response: {response.text}")
            
            if response.status_code == 200:
                data = response.json()
                token = data.get('access_token')
                expires_in = data.get('expires_in', 1799)  # Default 29m 59s
                
                if token:
                    # Cache for slightly less than expiration
                    cache.set(cache_key, token, expires_in - 60)
                    logger.debug(f"New token acquired: {token[:20]}...")
                    return token
                else:
                    logger.error("No token in response")
                    return None
            else:
                logger.error(f"Token request failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Token fetch error: {str(e)}", exc_info=True)
            return None
    
    def search_flight_offers(self, search_params):
        """Search for flights with comprehensive error handling"""
        try:
            # Log what we're receiving
            logger.info(f"=== AMADEUS API CALL STARTED ===")
            logger.info(f"Search params received: {search_params}")
            
            # Check if this is a retry attempt
            retry_attempt = search_params.get('_retry_attempt', 0)
            if retry_attempt > 0:
                original_date = search_params.get('_retry_original_date')
                logger.info(f"Retry attempt {retry_attempt} for date {search_params.get('departure_date')} (original: {original_date})")
            
            token = self._get_access_token()
            if not token:
                logger.error("No access token available")
                return [], "Authentication failed"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            # Build complete params - ONLY USE VALID PARAMETERS
            params = {
                'originLocationCode': search_params.get('origin', ''),
                'destinationLocationCode': search_params.get('destination', ''),
                'departureDate': search_params.get('departure_date', ''),
                'adults': search_params.get('adults', 1),
                'max': search_params.get('max_results', 50),
            }
            
            # Add return date if provided and not empty
            return_date = search_params.get('return_date')
            if return_date and return_date.strip():
                params['returnDate'] = return_date.strip()
                logger.info(f"Adding returnDate: {return_date}")
            
            # Add travel class if provided
            travel_class = search_params.get('travel_class')
            if travel_class and travel_class != 'ANY':
                params['travelClass'] = travel_class
                logger.info(f"Adding travelClass: {travel_class}")
            
            # Add children if provided (only if > 0)
            children = search_params.get('children', 0)
            if children and int(children) > 0:
                params['children'] = children
            
            # Add infants if provided (only if > 0)
            infants = search_params.get('infants', 0)
            if infants and int(infants) > 0:
                params['infants'] = infants
                params['infantInSeat'] = True  # Usually infants don't get seats, but API might need this
            
            # Add non-stop filter if requested
            non_stop = search_params.get('non_stop', False)
            if non_stop:
                params['nonStop'] = 'true'
            
            # NOTE: The following parameters are NOT valid for v2/shopping/flight-offers:
            # - includedCheckedBags (use v2/shopping/flight-offers/pricing for detailed pricing)
            # - currency (will be returned in the response automatically)
            
            logger.info(f"Final API params: {params}")
            
            # Log the full URL being called
            full_url = f"{self.base_url}/v2/shopping/flight-offers"
            logger.info(f"Calling URL: {full_url}")
            logger.info(f"Headers: Authorization: Bearer {token[:20]}...")
            
            # Make the API call
            response = requests.get(
                full_url,
                headers=headers,
                params=params,
                timeout=self.timeout
            )
            
            logger.info(f"=== API RESPONSE ===")
            logger.info(f"Status Code: {response.status_code}")
            
            # Try to parse the response
            try:
                response_json = response.json()
                logger.info(f"Response JSON keys: {list(response_json.keys())}")
                
                if 'errors' in response_json:
                    errors = response_json.get('errors', [])
                    logger.error(f"API Errors: {errors}")
                    for error in errors:
                        error_code = str(error.get('code', ''))
                        error_detail = error.get('detail', '').lower()
                        error_title = error.get('title', '')
                        logger.error(f"Error code: {error_code}, detail: {error_detail}")
                        
                        # ========== DETECT DATE-SPECIFIC ERRORS ==========
                        # Common Amadeus error codes for date/inventory issues
                        date_error_codes = [
                            '32691',  # No results found
                            '32076',  # No availability
                            '3926',   # No flights found
                            '38195',  # Invalid date
                            '38196',  # Date out of range
                            '38197',  # Date in past
                            '38198',  # Date too far in future
                        ]
                        
                        # Check for date/inventory errors
                        if any(code in error_code for code in date_error_codes):
                            logger.warning(f"Date availability error: {error_detail}")
                            if 'return' in error_detail and 'departure' in error_detail:
                                raise NoFlightsError(f"No flights available for both departure and return dates")
                            else:
                                raise NoFlightsError(f"No flights available on {search_params.get('departure_date')}")
                        
                        # Check for fare rule errors
                        fare_rule_terms = ['fare rule', 'minimum stay', 'advance purchase', 'validity', 'restricted']
                        if any(term in error_detail for term in fare_rule_terms):
                            logger.warning(f"Fare rule error: {error_detail}")
                            raise FareRuleError(f"Fare rules not met for selected dates: {error_title}")
                        
                        # Check for sold out errors
                        sold_out_terms = ['sold out', 'no availability', 'not available', 'no seats', 'fully booked']
                        if any(term in error_detail for term in sold_out_terms):
                            logger.warning(f"Sold out error: {error_detail}")
                            raise SoldOutError(f"Flights sold out for {search_params.get('departure_date')}")
                        
                        # Check for schedule gap errors
                        if 'schedule' in error_detail or 'connection' in error_detail:
                            logger.warning(f"Schedule gap error: {error_detail}")
                            raise ScheduleGapError(f"No valid itinerary available: {error_title}")
                        
                        # Check for minimum stay errors
                        if 'minimum stay' in error_detail or 'length of stay' in error_detail:
                            logger.warning(f"Minimum stay error: {error_detail}")
                            raise MinimumStayError(f"Minimum stay requirement not met: {error_title}")
                
                if 'data' in response_json:
                    flights_data = response_json.get('data', [])
                    logger.info(f"Number of flights found: {len(flights_data)}")
                    
                    # ========== CHECK IF NO FLIGHTS FOUND ==========
                    if not flights_data:
                        # Check if this was a one-way or round trip
                        is_roundtrip = 'returnDate' in params
                        
                        if is_roundtrip:
                            # For round trips, it could be either departure or return date
                            departure_date = search_params.get('departure_date')
                            return_date = search_params.get('return_date')
                            raise NoFlightsError(
                                f"No flights found for {departure_date} to {return_date}. "
                                f"Try adjusting your dates by 1-3 days."
                            )
                        else:
                            # For one-way trips
                            departure_date = search_params.get('departure_date')
                            raise NoFlightsError(f"No flights found for {departure_date}")
                    # ========== END CHECK ==========
                    
                    # DEBUG: Check if data has travelerPricings
                    if flights_data:
                        first_flight = flights_data[0]
                        has_traveler_pricings = 'travelerPricings' in first_flight
                        logger.info(f"First flight has travelerPricings: {has_traveler_pricings}")
                        if has_traveler_pricings:
                            logger.info(f"Number of travelerPricings: {len(first_flight['travelerPricings'])}")
                        
            except json.JSONDecodeError:
                logger.error(f"Response is not JSON: {response.text[:500]}")
                return [], f"Invalid API response format"
            
            if response.status_code == 200:
                data = response.json()
                flights_data = data.get('data', [])
                
                # Double-check if flights were found
                if not flights_data:
                    raise NoFlightsError(f"No flights found for {search_params.get('departure_date')}")
                
                flights = self._process_flight_data(flights_data)
                logger.info(f"Processed {len(flights)} flights")
                return flights, None
            
            elif response.status_code == 400:
                # Bad request - often date/parameter issues
                try:
                    error_data = response.json()
                    if 'errors' in error_data:
                        for error in error_data['errors']:
                            detail = error.get('detail', '').lower()
                            if 'date' in detail:
                                raise NoFlightsError(f"Invalid date format or unavailable date")
                    
                    return [], f"Invalid request parameters"
                except:
                    return [], f"Bad request: {response.text[:100]}"
            
            elif response.status_code == 404:
                # Not found - route or date not available
                return [], f"No flights available for this route on selected dates"
            
            elif response.status_code == 429:
                # Rate limited
                return [], f"Too many requests. Please wait a moment and try again"
            
            else:
                # Other errors
                error_msg = f"API Error: {response.status_code}"
                try:
                    error_data = response.json()
                    logger.error(f"Full error response: {error_data}")
                    
                    if 'errors' in error_data:
                        errors = error_data['errors']
                        error_details = []
                        
                        for err in errors:
                            detail = err.get('detail', 'No detail provided')
                            code = err.get('code', 'No code')
                            title = err.get('title', 'No title')
                            source = err.get('source', {}).get('parameter', 'unknown')
                            error_details.append(f"{code}: {title} - {detail}")
                            
                            # Check for date errors in error response
                            detail_lower = detail.lower()
                            if 'date' in detail_lower and ('invalid' in detail_lower or 'not available' in detail_lower or 'out of range' in detail_lower):
                                raise NoFlightsError(f"Date not available: {search_params.get('departure_date')}")
                        
                        error_msg = " | ".join(error_details)
                        
                except json.JSONDecodeError:
                    logger.error(f"Raw error response (first 1000 chars): {response.text[:1000]}")
                    error_msg = f"API Error {response.status_code}: {response.text[:200]}"
                
                return [], error_msg
                
        except NoFlightsError as e:
            # Re-raise specific error
            logger.warning(f"No flights error: {str(e)}")
            raise e
        except FareRuleError as e:
            logger.warning(f"Fare rule error: {str(e)}")
            raise e
        except SoldOutError as e:
            logger.warning(f"Sold out error: {str(e)}")
            raise e
        except MinimumStayError as e:
            logger.warning(f"Minimum stay error: {str(e)}")
            raise e
        except ScheduleGapError as e:
            logger.warning(f"Schedule gap error: {str(e)}")
            raise e
        except Exception as e:
            logger.error(f"Flight search error: {str(e)}", exc_info=True)
            return [], f"Error: {str(e)}"
    
   
    def format_duration(self, duration_str):
        """
        Format duration from ISO 8601 format (e.g., 'PT10H40M') to a readable format.
        Example: 'PT10H40M' -> '10h 40m'
        """
        if not duration_str:
            return ""
        
        # Remove 'PT' prefix
        duration = duration_str.replace("PT", "")
        hours = "0"
        minutes = "0"
        
        if "H" in duration:
            hours = duration.split("H")[0]
            duration = duration.split("H")[1] if "H" in duration else ""
        if "M" in duration:
            minutes = duration.split("M")[0]
        
        return f"{hours}h {minutes}m"

    def get_airline_names_batch(self, airline_codes):
        """
        Get multiple airline names at once (more efficient)
        Returns: Dict of {code: name}
        """
        if not airline_codes:
            return {}
        
        # Filter out empty codes
        airline_codes = [code for code in airline_codes if code]
        
        # Check cache first
        result = {}
        uncached_codes = []
        
        for code in airline_codes:
            cache_key = f"airline_name_{code}"
            cached_name = cache.get(cache_key)
            if cached_name:
                result[code] = cached_name
            else:
                uncached_codes.append(code)
        
        # If all were cached, return
        if not uncached_codes:
            return result
        
        try:
            token = self._get_access_token()
            if not token:
                # Fallback for all uncached codes
                for code in uncached_codes:
                    result[code] = self._get_airline_name_fallback(code)
                return result
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            # Batch lookup (Amadeus API supports up to 10 codes at once)
            batch_size = 10
            for i in range(0, len(uncached_codes), batch_size):
                batch = uncached_codes[i:i + batch_size]
                airline_codes_str = ','.join(batch)
                
                response = requests.get(
                    f"{self.base_url}/v1/reference-data/airlines",
                    headers=headers,
                    params={
                        'airlineCodes': airline_codes_str,
                        'limit': len(batch)
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    airlines = data.get('data', [])
                    
                    # Create mapping from response
                    api_mapping = {}
                    for airline in airlines:
                        code = airline.get('iataCode')
                        if code:
                            name = airline.get('businessName', '') or airline.get('commonName', '')
                            if name:
                                api_mapping[code] = name
                    
                    # Fill results and cache
                    for code in batch:
                        if code in api_mapping:
                            result[code] = api_mapping[code]
                            cache.set(f"airline_name_{code}", api_mapping[code], 86400)
                        else:
                            # Fallback for codes not found in API
                            fallback_name = self._get_airline_name_fallback(code)
                            result[code] = fallback_name
                            cache.set(f"airline_name_{code}", fallback_name, 86400)
                else:
                    # API failed for this batch, use fallback
                    for code in batch:
                        fallback_name = self._get_airline_name_fallback(code)
                        result[code] = fallback_name
            
            return result
            
        except Exception as e:
            logger.error(f"Error in batch airline lookup: {str(e)}")
            # Fallback for all remaining codes
            for code in uncached_codes:
                if code not in result:
                    result[code] = self._get_airline_name_fallback(code)
            return result

    def _get_airline_name_fallback(self, airline_code):
        """Fallback airline name mapping"""
        airline_mapping = {
            'FI': 'Icelandair',
            'AA': 'American Airlines',
            'DL': 'Delta Air Lines',
            'UA': 'United Airlines',
            'WN': 'Southwest Airlines',
            'B6': 'JetBlue Airways',
            'AS': 'Alaska Airlines',
            'NK': 'Spirit Airlines',
            'F9': 'Frontier Airlines',
            'HA': 'Hawaiian Airlines',
            'AC': 'Air Canada',
            'AF': 'Air France',
            'BA': 'British Airways',
            'LH': 'Lufthansa',
            'EK': 'Emirates',
            'QR': 'Qatar Airways',
            'SQ': 'Singapore Airlines',
            'CX': 'Cathay Pacific',
            'JL': 'Japan Airlines',
            'NH': 'ANA All Nippon Airways',
            'KE': 'Korean Air',
            'OZ': 'Asiana Airlines',
            'CA': 'Air China',
            'MU': 'China Eastern Airlines',
            'CZ': 'China Southern Airlines',
            'GA': 'Garuda Indonesia',
            'TG': 'Thai Airways',
            'QF': 'Qantas',
            'VA': 'Virgin Australia',
            'EY': 'Etihad Airways',
            'TK': 'Turkish Airlines',
            'SU': 'Aeroflot',
            'KL': 'KLM Royal Dutch Airlines',
            'IB': 'Iberia',
            'AZ': 'ITA Airways',
            'LX': 'Swiss International Air Lines',
            'SK': 'SAS Scandinavian Airlines',
            'LO': 'LOT Polish Airlines',
            'OS': 'Austrian Airlines',
            'SN': 'Brussels Airlines',
            'TP': 'TAP Air Portugal',
            'DY': 'Norwegian Air Shuttle',
            'FR': 'Ryanair',
            'U2': 'easyJet',
            'VY': 'Vueling Airlines',
            'LH': 'Lufthansa',
            'AF': 'Air France',
            'BA': 'British Airways',
            'KL': 'KLM',
            'IB': 'Iberia',
            'LX': 'Swiss',
            'OS': 'Austrian Airlines',
            'SK': 'SAS',
            'AY': 'Finnair',
            'LO': 'LOT Polish Airlines',
            'BT': 'airBaltic',
            'OU': 'Croatia Airlines',
            'JU': 'Air Serbia',
            'ME': 'Middle East Airlines',
            'MS': 'EgyptAir',
            'ET': 'Ethiopian Airlines',
            'SA': 'South African Airways',
            'KQ': 'Kenya Airways',
            'QR': 'Qatar Airways',
            'EK': 'Emirates',
            'EY': 'Etihad Airways',
            'SV': 'Saudia',
            'RJ': 'Royal Jordanian',
            'GF': 'Gulf Air',
            'WY': 'Oman Air',
            'FZ': 'Flydubai',
            'G9': 'Air Arabia',
            'J9': 'Jazeera Airways',
            'KU': 'Kuwait Airways',
        }
        
        return airline_mapping.get(airline_code, f"Airline ({airline_code})")
    
    def search_airports(self, keyword):
        """Search airports using Amadeus API"""
        try:
            token = self._get_access_token()
            if not token:
                return [], "Authentication failed"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            params = {
                'subType': 'AIRPORT',
                'keyword': keyword,
                'page[limit]': 10,
                'view': 'LIGHT'
            }
            
            response = requests.get(
                f"{self.base_url}/v1/reference-data/locations",
                headers=headers,
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                airports = []
                for location in data.get('data', []):
                    airports.append({
                        'code': location.get('iataCode', ''),
                        'name': location.get('name', ''),
                        'city': location.get('address', {}).get('cityName', ''),
                        'country': location.get('address', {}).get('countryName', ''),
                    })
                return airports, None
            else:
                return [], f"API Error: {response.status_code}"
                
        except Exception as e:
            logger.error(f"Airport search error: {str(e)}")
            return [], str(e)
        
    # Add this method to your AmadeusService class in amadeus_service.py
    def price_flights(self, flight_offer_data, travelers):
        """
        Price flight offers with traveler details
        Amadeus requires travelerPricings in the flight offer
        """
        try:
            logger.info(f"=== FLIGHT PRICING STARTED ===")
            logger.info(f"Pricing {len(travelers)} travelers")
            
            token = self._get_access_token()
            if not token:
                logger.error("No access token available for pricing")
                return None, "Authentication failed"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/vnd.amadeus+json'
            }
            
            # Get flight offer
            if isinstance(flight_offer_data, str):
                try:
                    flight_offer = json.loads(flight_offer_data)
                except json.JSONDecodeError:
                    logger.error("Invalid JSON in flight_offer_data")
                    return None, "Invalid flight data format"
            else:
                flight_offer = flight_offer_data
            
            # **DEBUG: Check segment IDs in travelerPricings**
            logger.info("=== DEBUG: CHECKING SEGMENT IDS ===")
            
            # Get all segment IDs from itineraries
            segment_ids_from_itineraries = []
            if 'itineraries' in flight_offer:
                for itinerary in flight_offer['itineraries']:
                    for segment in itinerary.get('segments', []):
                        seg_id = segment.get('id')
                        if seg_id:
                            segment_ids_from_itineraries.append(seg_id)
                            logger.info(f"Segment in itinerary: id={seg_id}, {segment.get('departure', {}).get('iataCode')}->{segment.get('arrival', {}).get('iataCode')}")
            
            # Get all segment IDs from travelerPricings
            segment_ids_from_pricings = []
            if 'travelerPricings' in flight_offer:
                for traveler_pricing in flight_offer['travelerPricings']:
                    for fare_detail in traveler_pricing.get('fareDetailsBySegment', []):
                        seg_id = fare_detail.get('segmentId')
                        if seg_id:
                            segment_ids_from_pricings.append(seg_id)
                            logger.info(f"Segment in travelerPricing: segmentId={seg_id}")
            
            logger.info(f"Segment IDs in itineraries: {segment_ids_from_itineraries}")
            logger.info(f"Segment IDs in travelerPricings: {segment_ids_from_pricings}")
            
            # Check if all segment IDs match
            missing_segments = [seg_id for seg_id in segment_ids_from_pricings if seg_id not in segment_ids_from_itineraries]
            if missing_segments:
                logger.error(f"Missing segment IDs in itineraries: {missing_segments}")
            
            # **FIX: Don't over-clean the data - send exactly what Amadeus gave us**
            # Create a clean copy but preserve the exact segment structure
            clean_flight_offer = {}
            
            # Keep only valid Amadeus fields
            valid_amadeus_fields = [
                'type', 'id', 'source', 'instantTicketingRequired',
                'nonHomogeneous', 'oneWay', 'isUpsellOffer',
                'lastTicketingDate', 'lastTicketingDateTime',
                'numberOfBookableSeats', 'itineraries', 'price',
                'pricingOptions', 'validatingAirlineCodes', 'travelerPricings'
            ]
            
            for field in valid_amadeus_fields:
                if field in flight_offer:
                    clean_flight_offer[field] = flight_offer[field]
            
            # Ensure type is set correctly
            clean_flight_offer['type'] = 'flight-offer'
            
            # **CRITICAL: Don't clean the segments too much!**
            # Only remove our custom fields, keep all Amadeus fields
            if 'itineraries' in clean_flight_offer:
                for itinerary in clean_flight_offer['itineraries']:
                    if 'segments' in itinerary:
                        for segment in itinerary['segments']:
                            # Remove only OUR custom fields, keep all Amadeus fields
                            if 'departure' in segment:
                                departure = segment['departure']
                                # Remove only city, country, airport_name, location if they exist
                                for field in ['city', 'country', 'airport_name', 'location']:
                                    if field in departure:
                                        del departure[field]
                            
                            if 'arrival' in segment:
                                arrival = segment['arrival']
                                # Remove only city, country, airport_name, location if they exist
                                for field in ['city', 'country', 'airport_name', 'location']:
                                    if field in arrival:
                                        del arrival[field]
            
            # **DEBUG: Log final structure**
            logger.info("=== FINAL PAYLOAD STRUCTURE ===")
            logger.info(f"Number of itineraries: {len(clean_flight_offer.get('itineraries', []))}")
            
            if clean_flight_offer.get('itineraries'):
                for i, itinerary in enumerate(clean_flight_offer['itineraries']):
                    logger.info(f"Itinerary {i+1}: {len(itinerary.get('segments', []))} segments")
                    for j, segment in enumerate(itinerary.get('segments', [])):
                        seg_id = segment.get('id', 'no-id')
                        logger.info(f"  Segment {j+1}: id={seg_id}, {segment.get('departure', {}).get('iataCode', '')}->{segment.get('arrival', {}).get('iataCode', '')}")
            
            logger.info(f"Number of travelerPricings: {len(clean_flight_offer.get('travelerPricings', []))}")
            if clean_flight_offer.get('travelerPricings'):
                for i, tp in enumerate(clean_flight_offer['travelerPricings']):
                    logger.info(f"TravelerPricing {i+1}: {len(tp.get('fareDetailsBySegment', []))} fareDetails")
                    for fd in tp.get('fareDetailsBySegment', []):
                        logger.info(f"  FareDetail segmentId: {fd.get('segmentId')}")
            
            # Prepare the payload
            payload = {
                "data": {
                    "type": "flight-offers-pricing",
                    "flightOffers": [clean_flight_offer],
                    "travelers": travelers
                }
            }
            
            # **DEBUG: Save payload to file for inspection**
            try:
                import os
                debug_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'debug_logs')
                os.makedirs(debug_dir, exist_ok=True)
                debug_file = os.path.join(debug_dir, f"pricing_payload_{int(time.time())}.json")
                with open(debug_file, 'w') as f:
                    json.dump(payload, f, indent=2)
                logger.info(f"Saved payload to: {debug_file}")
            except Exception as e:
                logger.error(f"Failed to save debug file: {e}")
            
            # Log the first 2000 chars of payload
            payload_str = json.dumps(payload)
            logger.info(f"Payload preview (first 1000 chars): {payload_str[:1000]}")
            
            response = requests.post(
                f"{self.base_url}/v1/shopping/flight-offers/pricing",
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            
            logger.info(f"Pricing response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Pricing successful!")
                return data, None
            else:
                error_msg = f"Pricing API Error: {response.status_code}"
                try:
                    error_data = response.json()
                    logger.error(f"Pricing error: {error_data}")
                    
                    if 'errors' in error_data:
                        errors = error_data['errors']
                        error_details = []
                        for err in errors:
                            detail = err.get('detail', 'No detail')
                            code = err.get('code', 'No code')
                            source = err.get('source', {}).get('pointer', '')
                            error_details.append(f"{code}: {detail} (at {source})")
                        error_msg = " | ".join(error_details)
                        
                except json.JSONDecodeError:
                    logger.error(f"Raw error: {response.text[:500]}")
                    error_msg = f"Raw error: {response.text[:200]}"
                
                return None, error_msg
                
        except Exception as e:
            logger.error(f"Pricing exception: {str(e)}", exc_info=True)
            return None, f"Error: {str(e)}"

    def create_booking(self, flight_offer, travelers, contacts):
        """
        Create a booking with Amadeus API
        Amadeus API endpoint: /v1/booking/flight-orders
        """
        try:
            logger.info(f"=== BOOKING CREATION STARTED ===")
            logger.info(f"Creating booking for {len(travelers)} travelers")
            
            token = self._get_access_token()
            if not token:
                logger.error("No access token available for booking")
                return None, "Authentication failed"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            # Prepare booking payload
            payload = {
                "data": {
                    "type": "flight-order",
                    "flightOffers": [flight_offer],
                    "travelers": travelers,
                    "remarks": {
                        "general": [{
                            "subType": "GENERAL_MISCELLANEOUS",
                            "text": "Booking created via FlightReserve system"
                        }]
                    },
                    "ticketingAgreement": {
                        "option": "DELAY_TO_CANCEL",
                        "delay": "6D"
                    },
                    "contacts": contacts
                }
            }
            
            logger.info(f"Booking payload prepared")
            
            url = f"{self.base_url}/v1/booking/flight-orders"
            logger.info(f"Calling booking endpoint: {url}")
            
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            
            logger.info(f"Booking response status: {response.status_code}")
            
            if response.status_code == 201:
                data = response.json()
                logger.info(f"Booking created successfully! Order ID: {data.get('data', {}).get('id', 'N/A')}")
                
                # Extract PNR if available
                if 'data' in data:
                    booking_data = data['data']
                    associated_records = booking_data.get('associatedRecords', [])
                    if associated_records:
                        pnr = associated_records[0].get('reference', '')
                        logger.info(f"PNR generated: {pnr}")
                
                return data, None
            else:
                error_msg = f"Booking API Error: {response.status_code}"
                try:
                    error_data = response.json()
                    logger.error(f"Full booking error response: {error_data}")
                    
                    if 'errors' in error_data:
                        errors = error_data['errors']
                        error_details = []
                        for err in errors:
                            code = err.get('code', 'No code')
                            title = err.get('title', 'No title')
                            detail = err.get('detail', 'No detail')
                            error_details.append(f"{code}: {title} - {detail}")
                        error_msg = " | ".join(error_details)
                        
                except json.JSONDecodeError:
                    logger.error(f"Raw booking error response: {response.text[:500]}")
                    error_msg = f"Booking Error {response.status_code}: {response.text[:200]}"
                
                return None, error_msg
                
        except requests.exceptions.Timeout:
            error_msg = "Booking request timed out"
            logger.error(error_msg)
            return None, error_msg
        except requests.exceptions.ConnectionError:
            error_msg = "Connection error while booking"
            logger.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"Booking exception: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return None, error_msg
        
    # In amadeus_service.py, add this method
    # Add these methods to your AmadeusService class in amadeus_service.py
    def get_airport_details_batch(self, airport_codes):
        """Get multiple airport city/country details at once"""
        if not airport_codes:
            return {}
        
        # Filter out empty codes
        airport_codes = [code for code in airport_codes if code and len(code) == 3]
        
        # Check cache first
        result = {}
        uncached_codes = []
        
        for code in airport_codes:
            cache_key = f"airport_details_{code}"
            cached_details = cache.get(cache_key)
            if cached_details:
                result[code] = cached_details
            else:
                uncached_codes.append(code)
        
        # If all were cached, return
        if not uncached_codes:
            return result
        
        try:
            token = self._get_access_token()
            if not token:
                # Use fallback for uncached codes
                for code in uncached_codes:
                    result[code] = self._get_airport_details_fallback(code)
                return result
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            # Amadeus API has limits, so batch in groups of 10
            batch_size = 10
            for i in range(0, len(uncached_codes), batch_size):
                batch = uncached_codes[i:i + batch_size]
                
                response = requests.get(
                    f"{self.base_url}/v1/reference-data/locations",
                    headers=headers,
                    params={
                        'subType': 'AIRPORT',
                        'keyword': ','.join(batch),
                        'page[limit]': len(batch)
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    airports = data.get('data', [])
                    
                    # Process API response
                    api_mapping = {}
                    for airport in airports:
                        code = airport.get('iataCode')
                        if code:
                            city = airport.get('address', {}).get('cityName', '')
                            country = airport.get('address', {}).get('countryName', '')
                            name = airport.get('name', '')
                            
                            api_mapping[code] = {
                                'city': city,
                                'country': country,
                                'name': name,
                                'full_name': f"{city}, {country}" if city and country else name
                            }
                    
                    # Fill results and cache
                    for code in batch:
                        if code in api_mapping:
                            result[code] = api_mapping[code]
                            cache.set(f"airport_details_{code}", api_mapping[code], 86400)  # 24 hours
                        else:
                            # Use fallback for codes not found in API
                            fallback_details = self._get_airport_details_fallback(code)
                            result[code] = fallback_details
                            cache.set(f"airport_details_{code}", fallback_details, 86400)
                else:
                    # API failed for this batch, use fallback
                    for code in batch:
                        fallback_details = self._get_airport_details_fallback(code)
                        result[code] = fallback_details
        
        except Exception as e:
            logger.error(f"Error in batch airport lookup: {str(e)}")
            # Use fallback for all remaining codes
            for code in uncached_codes:
                if code not in result:
                    result[code] = self._get_airport_details_fallback(code)
        
        return result

    def _get_airport_details_fallback(self, airport_code):
        """Fallback airport details mapping"""
        airport_mapping = {
            'ACC': {'city': 'Accra', 'country': 'Ghana', 'name': 'Kotoka International Airport'},
            'MUC': {'city': 'Munich', 'country': 'Germany', 'name': 'Munich Airport'},
            'JFK': {'city': 'New York', 'country': 'USA', 'name': 'John F. Kennedy International'},
            'LAX': {'city': 'Los Angeles', 'country': 'USA', 'name': 'Los Angeles International'},
            'LHR': {'city': 'London', 'country': 'UK', 'name': 'Heathrow Airport'},
            'CDG': {'city': 'Paris', 'country': 'France', 'name': 'Charles de Gaulle Airport'},
            'DXB': {'city': 'Dubai', 'country': 'UAE', 'name': 'Dubai International Airport'},
            'HND': {'city': 'Tokyo', 'country': 'Japan', 'name': 'Haneda Airport'},
            'SYD': {'city': 'Sydney', 'country': 'Australia', 'name': 'Sydney Airport'},
            'FRA': {'city': 'Frankfurt', 'country': 'Germany', 'name': 'Frankfurt Airport'},
            'AMS': {'city': 'Amsterdam', 'country': 'Netherlands', 'name': 'Amsterdam Schiphol'},
            'IST': {'city': 'Istanbul', 'country': 'Turkey', 'name': 'Istanbul Airport'},
            'SIN': {'city': 'Singapore', 'country': 'Singapore', 'name': 'Changi Airport'},
            'ICN': {'city': 'Seoul', 'country': 'South Korea', 'name': 'Incheon International'},
            'PEK': {'city': 'Beijing', 'country': 'China', 'name': 'Beijing Capital International'},
            'PVG': {'city': 'Shanghai', 'country': 'China', 'name': 'Shanghai Pudong International'},
            'ORD': {'city': 'Chicago', 'country': 'USA', 'name': "O'Hare International"},
            'DFW': {'city': 'Dallas', 'country': 'USA', 'name': 'Dallas/Fort Worth International'},
            'ATL': {'city': 'Atlanta', 'country': 'USA', 'name': 'Hartsfield-Jackson Atlanta'},
            'DEN': {'city': 'Denver', 'country': 'USA', 'name': 'Denver International'},
            'SFO': {'city': 'San Francisco', 'country': 'USA', 'name': 'San Francisco International'},
            'LAS': {'city': 'Las Vegas', 'country': 'USA', 'name': 'Harry Reid International'},
            'MIA': {'city': 'Miami', 'country': 'USA', 'name': 'Miami International'},
            'SEA': {'city': 'Seattle', 'country': 'USA', 'name': 'Seattle-Tacoma International'},
            'YYZ': {'city': 'Toronto', 'country': 'Canada', 'name': 'Toronto Pearson International'},
            'YVR': {'city': 'Vancouver', 'country': 'Canada', 'name': 'Vancouver International'},
            'GRU': {'city': 'São Paulo', 'country': 'Brazil', 'name': 'Guarulhos International'},
            'EZE': {'city': 'Buenos Aires', 'country': 'Argentina', 'name': 'Ministro Pistarini International'},
            'JNB': {'city': 'Johannesburg', 'country': 'South Africa', 'name': 'O.R. Tambo International'},
            'LOS': {'city': 'Lagos', 'country': 'Nigeria', 'name': 'Murtala Muhammed International'},
            'CAI': {'city': 'Cairo', 'country': 'Egypt', 'name': 'Cairo International'},
            'NBO': {'city': 'Nairobi', 'country': 'Kenya', 'name': 'Jomo Kenyatta International'},
            'ADD': {'city': 'Addis Ababa', 'country': 'Ethiopia', 'name': 'Bole International'},
            'CPT': {'city': 'Cape Town', 'country': 'South Africa', 'name': 'Cape Town International'},
            'DUR': {'city': 'Durban', 'country': 'South Africa', 'name': 'King Shaka International'},
            'MBA': {'city': 'Mombasa', 'country': 'Kenya', 'name': 'Moi International'},
            'KGL': {'city': 'Kigali', 'country': 'Rwanda', 'name': 'Kigali International'},
            'EBB': {'city': 'Entebbe', 'country': 'Uganda', 'name': 'Entebbe International'},
            'DAR': {'city': 'Dar es Salaam', 'country': 'Tanzania', 'name': 'Julius Nyerere International'},
            'ABJ': {'city': 'Abidjan', 'country': 'Ivory Coast', 'name': 'Félix-Houphouët-Boigny International'},
            'DKR': {'city': 'Dakar', 'country': 'Senegal', 'name': 'Blaise Diagne International'},
            'BKO': {'city': 'Bamako', 'country': 'Mali', 'name': 'Modibo Keita International'},
            'OUA': {'city': 'Ouagadougou', 'country': 'Burkina Faso', 'name': 'Thomas Sankara International'},
            'LFW': {'city': 'Lomé', 'country': 'Togo', 'name': 'Gnassingbé Eyadéma International'},
            'ABV': {'city': 'Abuja', 'country': 'Nigeria', 'name': 'Nnamdi Azikiwe International'},
            'PHC': {'city': 'Port Harcourt', 'country': 'Nigeria', 'name': 'Port Harcourt International'},
            'KAN': {'city': 'Kano', 'country': 'Nigeria', 'name': 'Mallam Aminu Kano International'},
            'ASU': {'city': 'Asunción', 'country': 'Paraguay', 'name': 'Silvio Pettirossi International'},
            'LIM': {'city': 'Lima', 'country': 'Peru', 'name': 'Jorge Chávez International'},
            'SCL': {'city': 'Santiago', 'country': 'Chile', 'name': 'Arturo Merino Benítez International'},
            'MEX': {'city': 'Mexico City', 'country': 'Mexico', 'name': 'Benito Juárez International'},
            'GDL': {'city': 'Guadalajara', 'country': 'Mexico', 'name': 'Miguel Hidalgo y Costilla International'},
            'CUN': {'city': 'Cancún', 'country': 'Mexico', 'name': 'Cancún International'},
            'PTY': {'city': 'Panama City', 'country': 'Panama', 'name': 'Tocumen International'},
            'SJO': {'city': 'San José', 'country': 'Costa Rica', 'name': 'Juan Santamaría International'},
            'MNL': {'city': 'Manila', 'country': 'Philippines', 'name': 'Ninoy Aquino International'},
            'BKK': {'city': 'Bangkok', 'country': 'Thailand', 'name': 'Suvarnabhumi Airport'},
            'DEL': {'city': 'Delhi', 'country': 'India', 'name': 'Indira Gandhi International'},
            'BOM': {'city': 'Mumbai', 'country': 'India', 'name': 'Chhatrapati Shivaji Maharaj International'},
            'MAD': {'city': 'Madrid', 'country': 'Spain', 'name': 'Adolfo Suárez Madrid–Barajas'},
            'BCN': {'city': 'Barcelona', 'country': 'Spain', 'name': 'Barcelona–El Prat'},
            'FCO': {'city': 'Rome', 'country': 'Italy', 'name': 'Leonardo da Vinci–Fiumicino'},
            'MXP': {'city': 'Milan', 'country': 'Italy', 'name': 'Malpensa Airport'},
            'ZRH': {'city': 'Zurich', 'country': 'Switzerland', 'name': 'Zurich Airport'},
            'VIE': {'city': 'Vienna', 'country': 'Austria', 'name': 'Vienna International'},
            'CPH': {'city': 'Copenhagen', 'country': 'Denmark', 'name': 'Copenhagen Airport'},
            'ARN': {'city': 'Stockholm', 'country': 'Sweden', 'name': 'Stockholm Arlanda'},
            'OSL': {'city': 'Oslo', 'country': 'Norway', 'name': 'Oslo Airport'},
            'HEL': {'city': 'Helsinki', 'country': 'Finland', 'name': 'Helsinki Airport'},
            'WAW': {'city': 'Warsaw', 'country': 'Poland', 'name': 'Warsaw Chopin'},
            'PRG': {'city': 'Prague', 'country': 'Czech Republic', 'name': 'Václav Havel Airport'},
            'BUD': {'city': 'Budapest', 'country': 'Hungary', 'name': 'Budapest Ferenc Liszt'},
            'ATH': {'city': 'Athens', 'country': 'Greece', 'name': 'Athens International'},
        }
        
        default_details = {
            'city': airport_code,
            'country': 'Unknown',
            'name': f'Airport ({airport_code})',
            'full_name': f'{airport_code}'
        }
        
        return airport_mapping.get(airport_code, default_details)

    # Then modify _process_flight_data to use airport details
    def _process_flight_data(self, flight_data):
        """
        Process flight data from Amadeus API and add airline and airport names
        PRESERVE ALL ORIGINAL FIELDS including travelerPricings
        """
        processed_flights = []
        
        # Collect all unique airline and airport codes for batch lookup
        all_airline_codes = set()
        all_airport_codes = set()
        
        for flight in flight_data:
            try:
                # Collect airline codes from this flight
                for itinerary in flight.get('itineraries', []):
                    for segment in itinerary.get('segments', []):
                        # Airline codes
                        carrier_code = segment.get('carrierCode', '')
                        if carrier_code:
                            all_airline_codes.add(carrier_code)
                        
                        # Airport codes
                        dep_code = segment.get('departure', {}).get('iataCode', '')
                        arr_code = segment.get('arrival', {}).get('iataCode', '')
                        if dep_code:
                            all_airport_codes.add(dep_code)
                        if arr_code:
                            all_airport_codes.add(arr_code)
                        
                        # Also check operating carrier
                        operating = segment.get('operating', {})
                        operating_code = operating.get('carrierCode', '')
                        if operating_code:
                            all_airline_codes.add(operating_code)
            except Exception as e:
                logger.error(f"Error collecting codes: {e}")
        
        # Get all airline names and airport details in batch
        airline_names_mapping = self.get_airline_names_batch(list(all_airline_codes))
        airport_details_mapping = self.get_airport_details_batch(list(all_airport_codes))
        
        # Process each flight
        for flight in flight_data:
            try:
                # IMPORTANT: Create a DEEP COPY to avoid modifying original
                import copy
                processed_flight = copy.deepcopy(flight)
                
                # DEBUG: Check for travelerPricings
                if 'travelerPricings' not in processed_flight:
                    logger.warning(f"Flight {flight.get('id', 'unknown')} missing travelerPricings!")
                else:
                    logger.debug(f"Flight {flight.get('id', 'unknown')} has {len(processed_flight['travelerPricings'])} travelerPricings")
                
                # Extract validating airline
                validating_airline = flight.get('validatingAirlineCodes', [''])[0]
                
                # Get airline names for all carriers in the flight
                airline_codes = set()
                airline_names = []
                
                # Collect all airline codes from segments
                for itinerary in flight.get('itineraries', []):
                    for segment in itinerary.get('segments', []):
                        carrier_code = segment.get('carrierCode', '')
                        if carrier_code:
                            airline_codes.add(carrier_code)
                
                # Get airline names from mapping
                for code in airline_codes:
                    airline_name = airline_names_mapping.get(code, f"Airline ({code})")
                    airline_names.append(airline_name)
                
                # Add airline data to flight WITHOUT removing original fields
                processed_flight['validating_airline'] = validating_airline
                processed_flight['validating_airline_name'] = airline_names_mapping.get(
                    validating_airline, 
                    f"Airline ({validating_airline})"
                )
                processed_flight['airline_names'] = airline_names
                
                # Add airport details to segments (for display only)
                for itinerary in processed_flight.get('itineraries', []):
                    for segment in itinerary.get('segments', []):
                        # Departure airport details
                        dep_code = segment.get('departure', {}).get('iataCode', '')
                        if dep_code in airport_details_mapping:
                            dep_details = airport_details_mapping[dep_code]
                            segment['departure']['city'] = dep_details.get('city', '')
                            segment['departure']['country'] = dep_details.get('country', '')
                            segment['departure']['airport_name'] = dep_details.get('name', '')
                            segment['departure']['location'] = f"{dep_details.get('city', '')}, {dep_details.get('country', '')}"
                        
                        # Arrival airport details
                        arr_code = segment.get('arrival', {}).get('iataCode', '')
                        if arr_code in airport_details_mapping:
                            arr_details = airport_details_mapping[arr_code]
                            segment['arrival']['city'] = arr_details.get('city', '')
                            segment['arrival']['country'] = arr_details.get('country', '')
                            segment['arrival']['airport_name'] = arr_details.get('name', '')
                            segment['arrival']['location'] = f"{arr_details.get('city', '')}, {arr_details.get('country', '')}"
                
                # Calculate stops
                stops = 0
                if flight.get('itineraries'):
                    first_itinerary = flight['itineraries'][0]
                    stops = len(first_itinerary.get('segments', [])) - 1
                processed_flight['stops'] = stops
                
                # Extract flight details for easy template access
                if flight.get('itineraries'):
                    first_itinerary = flight['itineraries'][0]
                    segments = first_itinerary.get('segments', [])
                    
                    if segments:
                        first_segment = segments[0]
                        last_segment = segments[-1]
                        
                        # Get airport details
                        origin_details = airport_details_mapping.get(
                            first_segment.get('departure', {}).get('iataCode', ''),
                            {}
                        )
                        destination_details = airport_details_mapping.get(
                            last_segment.get('arrival', {}).get('iataCode', ''),
                            {}
                        )
                        
                        # Add flat structure for template
                        processed_flight['origin'] = first_segment.get('departure', {}).get('iataCode', '')
                        processed_flight['destination'] = last_segment.get('arrival', {}).get('iataCode', '')
                        processed_flight['departure_time'] = first_segment.get('departure', {}).get('at', '')
                        processed_flight['arrival_time'] = last_segment.get('arrival', {}).get('at', '')
                        
                        # Add airport location details
                        processed_flight['origin_city'] = origin_details.get('city', '')
                        processed_flight['origin_country'] = origin_details.get('country', '')
                        processed_flight['origin_location'] = f"{origin_details.get('city', '')}, {origin_details.get('country', '')}"
                        
                        processed_flight['destination_city'] = destination_details.get('city', '')
                        processed_flight['destination_country'] = destination_details.get('country', '')
                        processed_flight['destination_location'] = f"{destination_details.get('city', '')}, {destination_details.get('country', '')}"
                        
                        # Extract duration from first itinerary
                        duration = first_itinerary.get('duration', '')
                        processed_flight['duration'] = duration
                        processed_flight['formatted_duration'] = self.format_duration(duration)
                        
                        # Extract travel class from travelerPricings if available
                        travel_class = 'ECONOMY'
                        try:
                            traveler_pricings = flight.get('travelerPricings', [])
                            if traveler_pricings:
                                fare_details = traveler_pricings[0].get('fareDetailsBySegment', [])
                                if fare_details:
                                    travel_class = fare_details[0].get('cabin', 'ECONOMY')
                        except:
                            pass
                        processed_flight['travel_class'] = travel_class
                
                # **CRITICAL: Store the ORIGINAL Amadeus data separately for pricing**
                # Create a clean copy of the original flight data without our modifications
                import copy
                original_amadeus_data = copy.deepcopy(flight)
                
                # Store it in the processed flight for later use
                processed_flight['_original_amadeus_data'] = original_amadeus_data
                
                processed_flights.append(processed_flight)
                
            except Exception as e:
                logger.error(f"Error processing flight: {e}")
                # On error, still include the original flight data
                processed_flights.append(flight)
        
        return processed_flights