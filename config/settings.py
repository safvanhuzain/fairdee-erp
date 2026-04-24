"""
Django settings for Fairdee Finance v1 (PostgreSQL + hybrid JSONB per architecture PDF).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-dev-only-change-in-production',
)

DEBUG = os.environ.get('DJANGO_DEBUG', 'true').lower() in ('1', 'true', 'yes')

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if h.strip()
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'apps.core',
    'apps.accounts',
    'apps.access',
    'apps.finance',
    'apps.desk',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Flow (e.g. :8765) iframes runserver (:8000). Different ports = different origins, so
# X-Frame-Options from clickjacking middleware blocks that preview. We cannot set
# X_FRAME_OPTIONS = None — Django 4.2's middleware calls .upper() on it and crashes.
# In DEBUG, drop the middleware so no framing header is sent (unless DJANGO_IFRAME_DENY).
_frame_deny = os.environ.get('DJANGO_IFRAME_DENY', '').lower() in ('1', 'true', 'yes')
if DEBUG and not _frame_deny:
    MIDDLEWARE = [mw for mw in MIDDLEWARE if mw != 'django.middleware.clickjacking.XFrameOptionsMiddleware']

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.desk.context_processors.desk_navigation',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

AUTH_USER_MODEL = 'accounts.User'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/app/'
LOGOUT_REDIRECT_URL = '/login/'

STATICFILES_DIRS = [BASE_DIR / 'static']

# Local default: SQLite (no Docker). Use PostgreSQL with USE_POSTGRES=1 + running server (e.g. docker compose).
_use_sqlite = os.environ.get('USE_SQLITE', 'true').lower() in ('1', 'true', 'yes')
_use_postgres = os.environ.get('USE_POSTGRES', '').lower() in ('1', 'true', 'yes')
if _use_postgres:
    _use_sqlite = False

if _use_sqlite:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('POSTGRES_DB', 'fairdee'),
            'USER': os.environ.get('POSTGRES_USER', 'fairdee'),
            'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'fairdee'),
            'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
            'PORT': os.environ.get('POSTGRES_PORT', '5432'),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}
