# flight_sys/core_backend/services/location_service.py
import geoip2.database
import os
from django.conf import settings
import logging
from django.core.cache import cache
import requests

logger = logging.getLogger(__name__)

class LocationService:
    """Service to detect user location and get airport information"""
    
    def __init__(self):
        self.geoip_db_path = os.path.join(
            settings.BASE_DIR, 
            'geo_data', 
            'GeoLite2-City.mmdb'
        )
        
        # Fallback IP lookup service
        self.fallback_services = [
            'https://ipapi.co/json/',
            'http://ip-api.com/json/',
            'https://api.ip.sb/geoip',
        ]
    
    def get_client_ip(self, request):
        """Get client IP address"""
        # Get the most likely real IP
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        
        # Remove port if present
        ip = ip.split(':')[0] if ':' in ip else ip
        
        # Localhost fallback
        if ip in ['127.0.0.1', 'localhost', '::1']:
            # Try to get public IP using external service
            try:
                response = requests.get('https://api.ipify.org?format=json', timeout=2)
                if response.status_code == 200:
                    ip = response.json().get('ip', ip)
            except:
                pass
        
        return ip
    
    def get_location_by_ip(self, ip_address):
        """Get location details from IP address"""
        cache_key = f"location_{ip_address}"
        cached_location = cache.get(cache_key)
        
        if cached_location:
            return cached_location
        
        location_info = {
            'ip': ip_address,
            'country': None,
            'country_code': None,
            'city': None,
            'latitude': None,
            'longitude': None,
        }
        
        # Try GeoIP2 database first
        if os.path.exists(self.geoip_db_path):
            try:
                reader = geoip2.database.Reader(self.geoip_db_path)
                response = reader.city(ip_address)
                
                location_info.update({
                    'country': response.country.name,
                    'country_code': response.country.iso_code,
                    'city': response.city.name,
                    'latitude': response.location.latitude,
                    'longitude': response.location.longitude,
                    'postal_code': response.postal.code,
                    'timezone': response.location.time_zone,
                })
                
                reader.close()
                cache.set(cache_key, location_info, 86400)  # Cache for 24 hours
                return location_info
                
            except Exception as e:
                logger.warning(f"GeoIP2 lookup failed for {ip_address}: {e}")
        
        # Fallback to online services
        for service_url in self.fallback_services:
            try:
                response = requests.get(service_url, timeout=3)
                if response.status_code == 200:
                    data = response.json()
                    
                    # Parse based on service
                    if 'ipapi.co' in service_url:
                        location_info.update({
                            'country': data.get('country_name'),
                            'country_code': data.get('country_code'),
                            'city': data.get('city'),
                            'latitude': data.get('latitude'),
                            'longitude': data.get('longitude'),
                        })
                    elif 'ip-api.com' in service_url:
                        location_info.update({
                            'country': data.get('country'),
                            'country_code': data.get('countryCode'),
                            'city': data.get('city'),
                            'latitude': data.get('lat'),
                            'longitude': data.get('lon'),
                        })
                    elif 'ip.sb' in service_url:
                        location_info.update({
                            'country': data.get('country'),
                            'country_code': data.get('country_code'),
                            'city': data.get('city'),
                            'latitude': data.get('latitude'),
                            'longitude': data.get('longitude'),
                        })
                    
                    if location_info['country']:
                        cache.set(cache_key, location_info, 86400)
                        return location_info
                        
            except Exception as e:
                logger.warning(f"Service {service_url} failed: {e}")
                continue
        
        # Final fallback - use default
        default_location = {
            'ip': ip_address,
            'country': 'United States',
            'country_code': 'US',
            'city': 'New York',
            'latitude': 40.7128,
            'longitude': -74.0060,
        }
        
        cache.set(cache_key, default_location, 3600)  # Cache for 1 hour
        return default_location
    
    def get_main_airport_for_country(self, country_code):
        """Get main airport for a country (based on common travel patterns)"""
        # Mapping of country codes to main international airports
        country_main_airports = {
            'US': 'JFK',  # John F. Kennedy International Airport
            'GB': 'LHR',  # London Heathrow
            'FR': 'CDG',  # Paris Charles de Gaulle
            'DE': 'FRA',  # Frankfurt Airport
            'JP': 'HND',  # Tokyo Haneda
            'CN': 'PEK',  # Beijing Capital
            'IN': 'DEL',  # Delhi Indira Gandhi
            'BR': 'GRU',  # São Paulo Guarulhos
            'RU': 'SVO',  # Moscow Sheremetyevo
            'CA': 'YYZ',  # Toronto Pearson
            'AU': 'SYD',  # Sydney Kingsford Smith
            'KR': 'ICN',  # Seoul Incheon
            'SG': 'SIN',  # Singapore Changi
            'TH': 'BKK',  # Bangkok Suvarnabhumi
            'AE': 'DXB',  # Dubai International
            'IT': 'FCO',  # Rome Fiumicino
            'ES': 'MAD',  # Madrid Barajas
            'NL': 'AMS',  # Amsterdam Schiphol
            'TR': 'IST',  # Istanbul Airport
            'MX': 'MEX',  # Mexico City
            'ZA': 'JNB',  # Johannesburg OR Tambo
            'EG': 'CAI',  # Cairo International
            'SA': 'RUH',  # Riyadh King Khalid
            'AR': 'EZE',  # Buenos Aires Ezeiza
            'CL': 'SCL',  # Santiago Arturo Merino Benitez
            'NZ': 'AKL',  # Auckland
            # Africa
            'NG': 'LOS',  # Lagos Murtala Muhammed
            'KE': 'NBO',  # Nairobi Jomo Kenyatta
            'GH': 'ACC',  # Accra Kotoka
            'DZ': 'ALG',  # Algiers Houari Boumediene
            'MA': 'CMN',  # Casablanca Mohammed V
        }
        
        return country_main_airports.get(country_code.upper(), '')
    
    def get_nearest_airports(self, latitude, longitude, limit=5):
        """Get nearest airports using Amadeus API"""
        try:
            # This requires Amadeus API access
            # You might need to implement this differently based on your data source
            from .amadeus_service import AmadeusService
            amadeus_service = AmadeusService()
            
            token = amadeus_service._get_access_token()
            if not token:
                return []
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            # Use Amadeus Reference Data API for airport search by location
            params = {
                'latitude': latitude,
                'longitude': longitude,
                'radius': 100,  # 100km radius
                'page[limit]': limit,
                'sort': 'relevance',
                'subType': 'AIRPORT'
            }
            
            response = requests.get(
                "https://test.api.amadeus.com/v1/reference-data/locations/airports",
                headers=headers,
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                airports = []
                for airport in data.get('data', []):
                    airports.append({
                        'code': airport.get('iataCode', ''),
                        'name': airport.get('name', ''),
                        'city': airport.get('address', {}).get('cityName', ''),
                        'country': airport.get('address', {}).get('countryName', ''),
                        'distance': airport.get('distance', {}).get('value', 0),
                    })
                return airports
                
        except Exception as e:
            logger.error(f"Error getting nearest airports: {e}")
        
        return []
    
    def get_location_context(self, request):
        """Get complete location context for template"""
        try:
            ip = self.get_client_ip(request)
            location = self.get_location_by_ip(ip)
            
            # Get main airport for country
            main_airport_code = self.get_main_airport_for_country(location['country_code'])
            
            # Try to get nearest airports if we have coordinates
            nearest_airports = []
            if location['latitude'] and location['longitude']:
                nearest_airports = self.get_nearest_airports(
                    location['latitude'], 
                    location['longitude']
                )
            
            context = {
                'user_location': location,
                'main_airport_code': main_airport_code,
                'nearest_airports': nearest_airports,
                'detected_city': location['city'] or location['country'],
                'detected_country': location['country'],
            }
            
            return context
            
        except Exception as e:
            logger.error(f"Error in get_location_context: {e}")
            return {
                'user_location': None,
                'main_airport_code': '',
                'nearest_airports': [],
                'detected_city': '',
                'detected_country': '',
            }