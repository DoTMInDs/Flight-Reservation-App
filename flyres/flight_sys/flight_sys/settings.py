"""
Django settings for flight_sys project.
Production-ready with all required configurations
"""
import os
import logging
from pathlib import Path
from datetime import timedelta
from decouple import config

logger = logging.getLogger(__name__)


from dotenv import load_dotenv

load_dotenv()


# os.environ
logger.info('here are the environment variables')
for k in os.environ:
    logger.info(f"{k}={os.environ[k]}")
logger.info('end')

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(exist_ok=True)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='django-insecure-dev-key-change-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '*').split(' ')
ALLOWED_HOSTS = [host.strip() for host in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1],flight-reservation-app-d3yv.onrender.com').split(',')]

CORS_ALLOW_ALL_ORIGINS = DEBUG
if not DEBUG:
    CORS_ALLOW_ALL_ORIGINS = [
        'https://flight-reservation-app-d3yv.onrender.com',
    ]

CSRF_TRUSTED_ORIGIN = os.environ.get('CSRF_TRUSTED_ORIGIN', 'http://localhost').split(' ')
CSRF_TRUSTED_ORIGIN = [
    'https://flight-reservation-app-d3yv.onrender.com',
]


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third-party apps
    'rest_framework',
    'corsheaders',
    'qr_code',
    
    # Local apps
    'core_backend',

]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'flight_sys.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'flight_sys.wsgi.application'

# PDF Configuration
PDF_GENERATOR = 'reportlab'  # Options: 'reportlab', 'weasyprint', 'auto'

# ReportLab settings
REPORTLAB_FONT_PATH = os.path.join(BASE_DIR, 'static/fonts/')

# WeasyPrint settings
WEASYPRINT_BASE_URL = 'http://localhost:8000'  # For loading external resources

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Database - Use SQLite for development, PostgreSQL for production
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Django REST Framework - SIMPLIFIED for development
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
        'user': '1000/day',
    }
}

# CORS Settings - Allow all for development
CORS_ALLOW_ALL_ORIGINS = DEBUG  # Only in development
if not DEBUG:
    CORS_ALLOWED_ORIGINS = config(
        'CORS_ALLOWED_ORIGINS', 
        default='http://localhost:3000'
    ).split(',')

# Amadeus API Configuration - Use environment variables
AMADEUS_API_KEY = config('AMADEUS_API_KEY', default='YOUR_TEST_API_KEY')
AMADEUS_API_SECRET = config('AMADEUS_API_SECRET', default='YOUR_TEST_API_SECRET')
AMADEUS_BASE_URL = config('AMADEUS_BASE_URL', default='https://test.api.amadeus.com')
AMADEUS_TOKEN_EXPIRY = 1800  # 30 minutes

# Email Configuration (for sending itineraries)
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@flightreserve.com')

# Login/Logout URLs
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
AUTH_USER_MODEL = 'core_backend.CustomUser'

# Security settings for production
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

# Cache TTL in seconds
CACHE_TTL = int(os.environ.get('CACHE_TTL', 300))

# GeoIP settings
GEOIP_PATH = os.path.join(BASE_DIR, 'geo_data')
GEOIP_CITY = 'GeoLite2-City.mmdb'

# Cache settings for location data
CACHE_LOCATION_TTL = 86400  # 24 hours

# Fallback settings for location services
LOCATION_DETECTION_ENABLED = True

# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'DEBUG',  # Change to DEBUG
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'amadeus.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'DEBUG',  # Change to DEBUG
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        '': {  # Root logger
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'core_backend': {  # Your app's logger
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
# Create logs directory if it doesn't exist
os.makedirs(os.path.join(BASE_DIR, 'logs'), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'media'), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'static'), exist_ok=True)