# core/settings.py
from pathlib import Path
import os
import dj_database_url
from dotenv import load_dotenv  # <-- load .env

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")  # <-- read environment variables from .env

DEBUG = os.getenv("DEBUG", "1") == "1"
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-please-change")

ALLOWED_HOSTS = os.getenv(
    "ALLOWED_HOSTS",
    "127.0.0.1,localhost,gr8date.com.au,www.gr8date.com.au,web-production-29e6.up.railway.app"
).split(",")

CSRF_TRUSTED_ORIGINS = [
    "https://gr8date.com.au",
    "https://www.gr8date.com.au",
    "https://web-production-29e6.up.railway.app",
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "pages.apps.PagesConfig",  # <-- important
    # --- allauth (headless) ---
    "django.contrib.sites",    # <<< required by allauth
    "allauth",                 # <<< allauth core
    "allauth.account",         # <<< allauth accounts
    # --- APIs ---
    "rest_framework",          # <-- added for API-first messaging & badges
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "core.middleware.PreviewLockMiddleware",   # lock middleware
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",  # <<< required by django-allauth
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # <<< FIXED name + moved after MessageMiddleware so messages work
    "core.middleware_onboarding.OnboardingAccessMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",  # required by allauth forms
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    DATABASES["default"] = dj_database_url.parse(
        DATABASE_URL, conn_max_age=600, ssl_require=False
    )

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Australia/Sydney"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Sites framework (needed by allauth)
SITE_ID = 1  # <<<

# Email-or-username login (keep your existing backends, add allauth AFTER them)
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "core.backends.EmailOrUsernameModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",  # <<< enable allauth auth backend
]

# Preview lock env toggles
PREVIEW_LOCK_ENABLED = os.getenv("PREVIEW_LOCK_ENABLED", "0") == "1"
PREVIEW_LOCK_PASSWORD = os.getenv("PREVIEW_LOCK_PASSWORD", "")
PREVIEW_LOCK_EXCLUDE_PATHS = os.getenv(
    "PREVIEW_LOCK_EXCLUDE_PATHS",
    "/_preview-lock/,/admin/,/static/,/media/"
).split(",")

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # SECURE_HSTS_SECONDS = 3600
    # SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # SECURE_HSTS_PRELOAD = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

# --- Auth redirects ---
LOGIN_URL = "/login/"
# was: LOGIN_REDIRECT_URL = "/dashboard/"
LOGIN_REDIRECT_URL = "/post-login/"   # <<< Step 5B.1 change
LOGOUT_REDIRECT_URL = "/"

# ----------------------------
# SMTP configuration (defaults to Microsoft 365; override via .env)
# ----------------------------
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.office365.com")  # <<< default adjusted
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "1") == "1"
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "0") == "1"  # keep 0 when using TLS/587
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")

DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "hello@gr8date.com.au")
SERVER_EMAIL = os.getenv("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", DEFAULT_FROM_EMAIL)

# Public base URL used in emails and notifications
SITE_BASE_URL = os.getenv(
    "SITE_BASE_URL",
    "https://www.gr8date.com.au" if not DEBUG else "http://127.0.0.1:8000"
)

# ----------------------------
# Django REST Framework (API-first messaging)
# ----------------------------
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
}

# ----------------------------
# Allauth (headless) behavior  (UPDATED to new keys)
# ----------------------------
ACCOUNT_LOGIN_METHODS = {"email"}                 # replaces deprecated ACCOUNT_AUTHENTICATION_METHOD
ACCOUNT_SIGNUP_FIELDS = ["email*"]                # replaces deprecated ACCOUNT_EMAIL_REQUIRED
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_CONFIRM_EMAIL_ON_GET = True
# IMPORTANT for preview flow: do NOT auto-login on confirm
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = False       # <<< Step 5B.1

# After-confirm redirects (to Marketing dashboard)
ACCOUNT_EMAIL_CONFIRMATION_ANONYMOUS_REDIRECT_URL = "/marketing/"
ACCOUNT_EMAIL_CONFIRMATION_AUTHENTICATED_REDIRECT_URL = "/marketing/"

# Use http locally so verification links open (no SSL on runserver)
if DEBUG:
    ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http"        # <<< local dev
else:
    ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"       # <<< production

