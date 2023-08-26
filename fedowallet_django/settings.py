"""
Django settings for fedowallet_django project.

Generated by 'django-admin startproject' using Django 4.2.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.2/ref/settings/
"""
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY')
if len(SECRET_KEY) != 50:
    raise ValueError('SECRET_KEY must be 50 characters long. run "./manage.py generate_secret_key"')

FERNET_KEY = os.environ.get('FERNET_KEY')
if len(FERNET_KEY) != 44:
    raise ValueError('FERNET_KEY must be 32bit Fernet key. run "./manage.py generate_fernet"')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True
ALLOWED_HOSTS = []
if DEBUG:
    ALLOWED_HOSTS.append('*')
ALLOWED_HOSTS.append(os.environ.get('DOMAIN', 'https://fedow.tibillet.ovh/'))

# Application definition

INSTALLED_APPS = [
    "daphne",
    "django.contrib.sites",
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'fedow_core',
    'solo',
    'django_extensions',
    'rest_framework',
    'rest_framework_api_key',
]

# if DEBUG:
#     INSTALLED_APPS += ['django_browser_reload']


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# if DEBUG:
#     MIDDLEWARE += ['django_browser_reload.middleware.BrowserReloadMiddleware']

ROOT_URLCONF = 'fedowallet_django.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'fedowallet_django.wsgi.application'
ASGI_APPLICATION = "fedowallet_django.asgi.application"

# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

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

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework_api_key.permissions.HasAPIKey",
    ]
}

# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'fr-fr'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

# Static filesSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/
STATIC_ROOT = os.path.join(BASE_DIR, "www", "static")
STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'fedow_core.FedowUser'

STRIPE_KEY_TEST = os.environ.get('STRIPE_KEY_TEST')
STRIPE_KEY = os.environ.get('STRIPE_KEY')
STRIPE_TEST = True
if os.environ.get('STRIPE_TEST') == 'False':
    STRIPE_TEST = False
    assert STRIPE_KEY is not None
