from pathlib import Path
import os
import dj_database_url
import sentry_sdk
import ssl
from sentry_sdk.integrations.django import DjangoIntegration
from corsheaders.defaults import default_headers

# -----------------------------------------------------
# Base paths & Environment Detection
# -----------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
IS_RENDER = os.getenv('RENDER', False)  # Render sets this automatically

# -----------------------------------------------------
# Core settings
# -----------------------------------------------------
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret-key-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "1") not in ("0", "false", "False") and not IS_RENDER

# ALLOWED_HOSTS - NO https:// prefix!
ALLOWED_HOSTS = [
    "localhost", 
    "127.0.0.1",
    "timetracker-api-k375.onrender.com",
    "time-capture-fullstack-frontend.onrender.com",
    "timetracker-api-rebuild.onrender.com",   # NEW — for rebuild work

    # Add your custom domain here when ready
]

AGENT_KEY = os.getenv("AGENT_KEY") or os.getenv("AGENT_API_KEY", "")
AGENT_POST_URL = os.getenv("AGENT_POST_URL", "")
AGENT_AUTO_PROVISION = True
USE_AUTH = False

TIME_ZONE = 'America/New_York'
CELERY_TIMEZONE = 'America/New_York'
USE_TZ = True

# -----------------------------------------------------
# Applications
# -----------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "corsheaders",
    "tracker.apps.TrackerConfig",
    "django_celery_results",
    "django_celery_beat",
    "mobile",
]

SITE_ID = 1
ACCOUNT_AUTHENTICATION_METHOD = "username_email"
ACCOUNT_EMAIL_REQUIRED = False
ACCOUNT_EMAIL_VERIFICATION = "none"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# -----------------------------------------------------
# Middleware
# -----------------------------------------------------
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# -----------------------------------------------------
# Celery config
# -----------------------------------------------------
_redis_url = os.getenv("REDIS_URL", os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"))

# Append ssl_cert_reqs for rediss:// URLs (required by Celery Redis backend)
if _redis_url.startswith("rediss://") and "ssl_cert_reqs" not in _redis_url:
    _redis_url += "?ssl_cert_reqs=CERT_NONE" if "?" not in _redis_url else "&ssl_cert_reqs=CERT_NONE"

CELERY_BROKER_URL = _redis_url
CELERY_RESULT_BACKEND = _redis_url
CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "False").lower() == "true"
CELERY_TASK_TIME_LIMIT = 60 * 3
CELERY_ACKS_LATE = True

# celery.py or settings
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_MAX_RETRIES = 10
CELERY_BROKER_TRANSPORT_OPTIONS = {
    'visibility_timeout': 3600,
    'socket_keepalive': True,
    'retry_on_timeout': True,
}

CELERY_BROKER_USE_SSL = {
    'ssl_cert_reqs': ssl.CERT_NONE
}
CELERY_RESULT_BACKEND_USE_SSL = {
    'ssl_cert_reqs': ssl.CERT_NONE
}

import warnings
warnings.filterwarnings('ignore', message='.*ssl_cert_reqs.*CERT_NONE.*')

# -----------------------------------------------------
# URL / WSGI / ASGI
# -----------------------------------------------------
ROOT_URLCONF = "timeserver.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "timeserver.wsgi.application"
ASGI_APPLICATION = "timeserver.asgi.application"

# -----------------------------------------------------
# Database - Works with Render's DATABASE_URL
# -----------------------------------------------------
# -----------------------------------------------------
# Database (Neon Postgres)
# -----------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB"),
        "USER": os.getenv("POSTGRES_USER"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "HOST": os.getenv("POSTGRES_HOST"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "OPTIONS": {"sslmode": "require"},
    }
}

# -----------------------------------------------------
# Password validation
# -----------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# -----------------------------------------------------
# Sentry
# -----------------------------------------------------
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=float(os.getenv("SENTRY_TRACES", "0.0")),
        profiles_sample_rate=float(os.getenv("SENTRY_PROFILES", "0.0")),
        send_default_pii=False,
        environment=os.getenv("ENV", "dev"),
    )

OPENAI_TIMEOUT_SEC = float(os.getenv("OPENAI_TIMEOUT_SEC", "8"))
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "2"))

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
AI_CLASSIFY_MODEL = "gpt-4o-mini"
AI_CLASSIFY_CACHE_TTL = 86400 * 7       # 7 days
AI_CLASSIFY_RATE_LIMIT = 100            # per org per hour
AI_CLASSIFY_ENABLED_PLANS = None        # None = all plans, or ["professional", "executive"]

# -----------------------------------------------------
# Internationalization
# -----------------------------------------------------
LANGUAGE_CODE = "en-us"
USE_I18N = True

# -----------------------------------------------------
# Static & Media
# -----------------------------------------------------
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Render proxy settings
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# -----------------------------------------------------
# Security Settings (Production vs Dev)
# -----------------------------------------------------
if IS_RENDER or not DEBUG:
    # Production security settings
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
else:
    # Development - relaxed security
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_SSL_REDIRECT = False
    SECURE_HSTS_SECONDS = 0

# Cookie settings (common to both)
CSRF_COOKIE_HTTPONLY = False  # JS needs to read csrftoken
CSRF_COOKIE_SAMESITE = "None"
SESSION_COOKIE_SAMESITE = "None"
CSRF_COOKIE_NAME = "csrftoken"

# -----------------------------------------------------
# CORS Configuration
# -----------------------------------------------------
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    # Local development
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    # Production
    "https://timetracker-frontend-9y52.onrender.com",  # ← ADD THIS
    "https://timetracker.mavops.ai",  # ← ADD THIS TOO for custom domain

]

CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-agent-key", 
    "agent-key", 
    "authorization",
    "x-agent-user", 
    "x-agent-host",
    "x-admin-secret",

]

# -----------------------------------------------------
# CSRF Configuration
# -----------------------------------------------------
CSRF_TRUSTED_ORIGINS = [
    # Local development
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:7123",
    "http://127.0.0.1:7123",
    "http://localhost:8080",
    # Production
    "https://timetracker.mavops.ai",
    "https://timetracker-frontend-9y52.onrender.com",  # ← ADD
    "https://timetracker-api-k375.onrender.com",        # ← ADD (API itself)
]

# Optional: URLs that should be exempt from CSRF (like raw agent events)
CSRF_EXEMPT_URLS = ["/tracker/raw-events/"]

# Email configuration (for sending invites)
# Email Configuration
# EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_HOST = 'smtp.gmail.com'
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = os.environ.get('EMAIL_USER')
# EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_PASSWORD')
# DEFAULT_FROM_EMAIL = os.environ.get('EMAIL_USER')

# -----------------------------------------------------
# Django REST Framework
# -----------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "tracker.auth.AgentKeyAuthentication",
        "tracker.auth.BearerTokenAuthentication",  # ✅ Add this first
        # "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "agent_ingest": "6000/minute",
        "ui_read": "120/minute",
        "ui_write": "60/minute",
        "ai_generate": "20/minute",
        "public_hello": "120/minute",
        "anon": "100/minute",
        "user": "1000/minute",
    },
}

# -----------------------------------------------------
# SendGrid
# -----------------------------------------------------

SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
DEFAULT_FROM_EMAIL = 'noreply@mavops.ai'
DEFAULT_REPLY_TO_EMAIL = 'dan@mavops.ai'
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'https://timetracker.mavops.ai')

# -----------------------------------------------------
# Stripe
# -----------------------------------------------------

STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')

STRIPE_PRICE_PROFESSIONAL_MONTHLY = os.environ.get("STRIPE_PRICE_PROFESSIONAL_MONTHLY")
STRIPE_PRICE_PROFESSIONAL_YEARLY  = os.environ.get("STRIPE_PRICE_PROFESSIONAL_YEARLY")

STRIPE_PRICE_EXECUTIVE_MONTHLY    = os.environ.get("STRIPE_PRICE_EXECUTIVE_MONTHLY")
STRIPE_PRICE_EXECUTIVE_YEARLY     = os.environ.get("STRIPE_PRICE_EXECUTIVE_YEARLY")


# QuickBooks
QUICKBOOKS_CLIENT_ID = os.environ.get('QUICKBOOKS_CLIENT_ID', default='')
QUICKBOOKS_CLIENT_SECRET = os.environ.get('QUICKBOOKS_CLIENT_SECRET', default='')
QUICKBOOKS_REDIRECT_URI = os.environ.get('QUICKBOOKS_REDIRECT_URI', default='')
QUICKBOOKS_API_BASE = os.getenv('QUICKBOOKS_API_BASE', 'https://quickbooks.api.intuit.com')

QB_WEBHOOK_VERIFIER_TOKEN = os.environ.get('QB_WEBHOOK_VERIFIER_TOKEN', '')

# Xero
XERO_CLIENT_ID = os.environ.get('XERO_CLIENT_ID', default='')
XERO_CLIENT_SECRET = os.environ.get('XERO_CLIENT_SECRET', default='')
XERO_REDIRECT_URI = os.environ.get('XERO_REDIRECT_URI', default='')

# Microsoft Graph (Calendar Integration)
MS_GRAPH_CLIENT_ID = os.environ.get('MS_GRAPH_CLIENT_ID', '')
MS_GRAPH_CLIENT_SECRET = os.environ.get('MS_GRAPH_CLIENT_SECRET', '')
MS_GRAPH_REDIRECT_URI = os.environ.get(
    'MS_GRAPH_REDIRECT_URI',
    'https://timetracker-api-k375.onrender.com/api/calendar/auth/callback/',
)

# -----------------------------------------------------
# Logging
# -----------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": "DEBUG" if DEBUG else "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}