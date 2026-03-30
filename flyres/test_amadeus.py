# test_amadeus.py
import requests
from django.conf import settings

# Test token generation
def test_token():
    response = requests.post(
        "https://test.api.amadeus.com/v1/security/oauth2/token",
        data={
            'grant_type': 'client_credentials',
            'client_id': settings.AMADEUS_API_KEY,
            'client_secret': settings.AMADEUS_API_SECRET
        },
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    
    if response.status_code == 200:
        token = response.json()['access_token']
        
        # Test flight search
        headers = {'Authorization': f'Bearer {token}'}
        params = {
            'originLocationCode': 'JFK',
            'destinationLocationCode': 'LAX',
            'departureDate': '2026-03-19',
            'adults': 1
        }
        
        search_response = requests.get(
            "https://test.api.amadeus.com/v2/shopping/flight-offers",
            headers=headers,
            params=params
        )
        
        print(f"\nSearch Status: {search_response.status_code}")
        print(f"Search Response: {search_response.json()}")