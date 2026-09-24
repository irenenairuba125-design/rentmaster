"""
RENTMASTER settings.

Secrets and deployment options are read from environment variables so the same
file works for local development and production.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return env(name, str(default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = env("RENTMASTER_SECRET_KEY", "django-insecure-dev-only-change-me")
DEBUG = env_bool("RENTMASTER_DEBUG", True)
ALLOWED_HOSTS = [h for h in env("RENTMASTER_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in env("RENTMASTER_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "apps.accounts",
    "apps.core",
    "apps.properties",
    "apps.tenants",
    "apps.billing",
    "apps.maintenance",
    "apps.finance",
    "apps.inspections",
    "apps.vacancies",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.CurrentUserMiddleware",
    "apps.accounts.middleware.Require2FAMiddleware",
]

ROOT_URLCONF = "rentmaster.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "rentmaster.wsgi.application"

# SQLite for development; set RENTMASTER_DB_ENGINE=postgresql (plus the
# RENTMASTER_DB_* variables) for production.
if env("RENTMASTER_DB_ENGINE") == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("RENTMASTER_DB_NAME", "rentmaster"),
            "USER": env("RENTMASTER_DB_USER", "rentmaster"),
            "PASSWORD": env("RENTMASTER_DB_PASSWORD", ""),
            "HOST": env("RENTMASTER_DB_HOST", "localhost"),
            "PORT": env("RENTMASTER_DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Kampala"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
PRIVATE_MEDIA_ROOT = BASE_DIR / "private_media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Session / transport security
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("RENTMASTER_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # Bearer tokens (mobile app) are issued only after two-factor login where enabled.
        # HTTP Basic is deliberately absent: it would let a password alone bypass 2FA.
        "apps.accounts.authentication.BearerTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

EMAIL_BACKEND = env("RENTMASTER_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("RENTMASTER_FROM_EMAIL", "RENTMASTER <no-reply@rentmaster.local>")

# ---------------------------------------------------------------------------
# RENTMASTER business settings
# ---------------------------------------------------------------------------
RENTMASTER = {
    "CURRENCY": "UGX",
    "COMPANY_NAME": env("RENTMASTER_COMPANY_NAME", "RENTMASTER"),
    "LEASE_EXPIRY_ALERT_DAYS": 30,
    "RENT_REMINDER_DAYS_BEFORE": 3,
    "SERIOUS_ARREARS_DAYS": 30,
    # Base URL used in receipts' QR codes and notification links.
    "SITE_URL": env("RENTMASTER_SITE_URL", "http://127.0.0.1:8000"),
    # Roles forced to set up two-factor authentication, e.g. "SUPER_ADMIN,ACCOUNTANT".
    "REQUIRE_2FA_ROLES": [r for r in env("RENTMASTER_REQUIRE_2FA_ROLES", "").split(",") if r],
}
BACKUP_DIR = Path(env("RENTMASTER_BACKUP_DIR", BASE_DIR / "backups"))

# Payment providers. A provider with missing credentials is treated as "not
# configured": payments through it stay PENDING and are never auto-verified.
PAYMENT_PROVIDERS = {
    "MTN_MOMO": {
        "BASE_URL": env("MTN_MOMO_BASE_URL", "https://sandbox.momodeveloper.mtn.com"),
        "TARGET_ENVIRONMENT": env("MTN_MOMO_TARGET_ENV", "sandbox"),
        "SUBSCRIPTION_KEY": env("MTN_MOMO_SUBSCRIPTION_KEY", ""),
        "API_USER": env("MTN_MOMO_API_USER", ""),
        "API_KEY": env("MTN_MOMO_API_KEY", ""),
        "CURRENCY": env("MTN_MOMO_CURRENCY", "UGX"),  # sandbox uses EUR
    },
    "AIRTEL_MONEY": {
        "BASE_URL": env("AIRTEL_BASE_URL", "https://openapiuat.airtel.africa"),
        "CLIENT_ID": env("AIRTEL_CLIENT_ID", ""),
        "CLIENT_SECRET": env("AIRTEL_CLIENT_SECRET", ""),
        "COUNTRY": "UG",
        "CURRENCY": "UGX",
    },
}

# SMS: set AFRICASTALKING_USERNAME / AFRICASTALKING_API_KEY to send real SMS;
# otherwise messages are written to the log.
SMS = {
    "USERNAME": env("AFRICASTALKING_USERNAME", ""),
    "API_KEY": env("AFRICASTALKING_API_KEY", ""),
    "SENDER_ID": env("AFRICASTALKING_SENDER_ID", ""),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"rentmaster": {"handlers": ["console"], "level": "INFO"}},
}

# Faster password hashing when running the test suite.
import sys  # noqa: E402

if "test" in sys.argv:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
