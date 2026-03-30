from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from .views_template  import FlightSearchView, PriceValidationView, CreateReservationView

urlpatterns = [
    path('', views.home, name='home'),


    # Authentication
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('profile/', views.profile_view, name='profile'),

    # Password reset
    path('reset_password/', auth_views.PasswordResetView.as_view(template_name='core/accounts/password/password_reset.html',
                                                                 email_template_name='core/accounts/password/password_reset_email.html'),
                                                                   name='reset_password'),
    path('reset_password_sent/', auth_views.PasswordResetDoneView.as_view(template_name='core/accounts/password/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/',auth_views.PasswordResetConfirmView.as_view(template_name='core/accounts/password/password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset_password_complete/', auth_views.PasswordResetCompleteView.as_view(template_name='core/accounts/password/password_reset_complete.html'), name='password_reset_complete'),

    
    path('flights/search/', views.flight_search, name='flight_search'),
    path('flights/results/', views.flight_search_results, name='flight_search_results'),
    path('flights/select/', views.select_flight, name='select_flight'),
    
    # AJAX endpoints
    path('ajax/airports/search/', views.search_airports_ajax, name='search_airports_ajax'),
    path('ajax/flights/status/', views.flight_status_ajax, name='flight_status_ajax'),
    path('search-airports/', views.search_airports_ajax, name='search_airports'),
    
    # Booking
    path('booking/form/', views.booking_form, name='booking_form'),
    path('booking/price/', views.price_flight, name='price_flight'),
    path('booking/create/', views.create_booking, name='create_booking'),
    path('booking/confirmation/<str:pnr>/', views.booking_confirmation, name='booking_confirmation'),
    path('booking/review/', views.booking_review, name='booking_review'),
    
    # User bookings
    path('my-bookings/', views.my_bookings, name='my_bookings'),
    path('booking/<str:pnr>/', views.view_booking, name='view_booking'),
    path('booking/<str:pnr>/download/', views.download_itinerary, name='download_itinerary'),
    path('booking/<str:pnr>/download-official/', views.download_official_itinerary, name='download_official_itinerary'),
    # path('api/booking/<str:pnr>/', views.api_booking_details, name='api_booking_details'),
    path('api/booking-details/<str:pnr>/', views.api_booking_details, name='api_booking_details'),

    # In urls.py
    path('debug/pricing/', views.debug_pricing_data, name='debug_pricing'),
    path('debug/flight-offer/', views.debug_flight_offer, name='debug_flight_offer'),
    path('debug/pricing-payload/', views.debug_pricing_payload, name='debug_pricing_payload'),
    path('debug/flight-offer/', views.debug_flight_offer_data, name='debug_flight_offer'),
]
