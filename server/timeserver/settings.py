from pathlib import Path
import os
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

# -----------------------------------------------------
# Base paths
# -----------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# -----------------------------------------------------
# Core settings
# -----------------------------------------------------
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret-key-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "1") not in ("0", "false", "False")
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")]

AGENT_KEY = os.getenv("AGENT_KEY") or os.getenv("AGENT_API_KEY", "")
AGENT_POST_URL = os.getenv("AGENT_POST_URL", "")

AGENT_AUTO_PROVISION = True

USE_AUTH = False  # so the frontend can hit the API without JWT

TIME_ZONE = 'America/New_York'  # or your actual timezone
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

]

SITE_ID = 1
ACCOUNT_AUTHENTICATION_METHOD = "username_email"
ACCOUNT_EMAIL_REQUIRED = False
ACCOUNT_EMAIL_VERIFICATION = "none"  # can switch on later
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'DEBUG',
    },
}

# -----------------------------------------------------
# Middleware
# -----------------------------------------------------
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# Celery config (safe defaults)
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/0")
CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "False").lower() == "true"
CELERY_TASK_TIME_LIMIT = 60 * 3  # 3 minutes per task
CELERY_ACKS_LATE = True

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


# -----------------------------------------------------
# Internationalization
# -----------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "America/New_York")
USE_I18N = True
USE_TZ = True

# -----------------------------------------------------
# Static & Media
# -----------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# -----------------------------------------------------
# Security & CSRF
# -----------------------------------------------------
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") in ("1", "true", "True")
CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", "0") in ("1", "true", "True")
CSRF_COOKIE_HTTPONLY = False           # <-- JS can read csrftoken
# CSRF_COOKIE_HTTPONLY = os.getenv("CSRF_COOKIE_HTTPONLY", "1") in ("1", "true", "True")
CSRF_COOKIE_SAMESITE = os.getenv("CSRF_COOKIE_SAMESITE", "Lax")  # can be "Strict" or "None"
CSRF_COOKIE_NAME = os.getenv("CSRF_COOKIE_NAME", "csrftoken")

SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "0") in ("1", "true", "True")
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("SECURE_HSTS_INCLUDE_SUBDOMAINS", "0") in ("1", "true", "True")
SECURE_HSTS_PRELOAD = os.getenv("SECURE_HSTS_PRELOAD", "0") in ("1", "true", "True")

# Trusted CSRF origins (parse from comma-separated env var)
_raw_csrf = os.getenv("CSRF_TRUSTED_ORIGINS", "http://localhost:5174,http://127.0.0.1:5174, http://localhost:5174")
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _raw_csrf.split(",") if o.strip()]

# Optional helper for excluding specific endpoints (like APIs)
CSRF_EXEMPT_URLS = ["/tracker/raw-events/"]  # you can append API endpoints here

# -----------------------------------------------------
# Security & CSRF / CORS for local dev
# -----------------------------------------------------
from corsheaders.defaults import default_headers

# Your SPA runs on http://localhost:5173, API on http://localhost:7123
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# CORS
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    # keep other dev hosts if you actually use them:
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    # prod preview you had:
    "https://463d01aa088f43d1ae615127e617af8e-fcaec2f20afa415aa44dbb66c.fly.dev",
]
CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-agent-key", "agent-key", "authorization",
    "x-agent-user", "x-agent-host",
]

# CSRF: TRUSTED ORIGINS MUST include scheme + host (+port)
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:7123",
    "http://127.0.0.1:7123",
    # add https variants if you test with TLS locally
]

# Cookies (dev-friendly)
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = False        # True only behind https
CSRF_COOKIE_SECURE = False           # True only behind https
CSRF_COOKIE_HTTPONLY = False         # must be False so JS can read csrftoken

CSRF_COOKIE_NAME = os.getenv("CSRF_COOKIE_NAME", "csrftoken")

# If you want to relax SSL redirect in dev:
SECURE_SSL_REDIRECT = False

# -----------------------------------------------------
# Django REST Framework
# -----------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "tracker.auth.AgentKeyAuthentication",
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # generous for agent firehose in prod; set to "" or remove in dev if needed
        "agent_ingest": "6000/minute",     # bursts OK, adjust as you like

        # UI
        "ui_read": "120/minute",           # list/detail GETs
        "ui_write": "60/minute",           # POST/PUT/DELETE from the UI

        # AI work (expensive)
        "ai_generate": "20/minute",        # AI suggestions / timecard gen

        # public pings/identity (optional guard)
        "public_hello": "120/minute",

        # legacy buckets (used only if you explicitly apply User/AnonRateThrottle)
        "anon": "100/minute",
        "user": "1000/minute",
    },
}
# (Optional) If you truly need to exempt a path from CSRF, you'll need custom middleware.
# The CSRF_EXEMPT_URLS list by itself isn't used by Django.


# -----------------------------------------------------
# Logging
# -----------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "DEBUG" if DEBUG else "INFO"},
}
