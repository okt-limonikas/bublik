"""
Django settings for bublik project.

Generated by 'django-admin startproject' using Django 1.11.

For more information on this file, see
https://docs.djangoproject.com/en/1.11/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.11/ref/settings/
"""

import os
import sys
import importlib.util

from datetime import timedelta

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Bublik UI repo location
BUBLIK_UI_DIR = os.getenv('BUBLIK_UI_DIR', "/app/bublik-ui")

# Bublik UI docs directory
BUBLIK_UI_DOCS_DIR = os.getenv('BUBLIK_UI_DOCS_DIR', "/app/bublik/docs")

BUBLIK_UI_STATIC = f"{BUBLIK_UI_DIR}/dist/apps/bublik"
# Bublik host for urls i.e."http://bublik"
BUBLIK_HOST = os.getenv('BUBLIK_HOST', "http://bublik")
# Staic web files
BUBLIK_WEB_STATIC = os.getenv('BUBLIK_WEB_STATIC', "")

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.11/howto/deployment/checklist/

SECRET_KEY = os.getenv("SECRET_KEY")

DEBUG = int(os.getenv("DEBUG", 0))

ALLOWED_HOSTS = ["*"]

# For debug panel. Note, that you might need
# ./scripts/manage collectstatic
INTERNAL_IPS = ['127.0.0.1']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_filters',
    'django_extensions',
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'rest_framework.authtoken',
    'bublik.data',
    'bublik.interfaces',
    'bublik.representation',
    'drf_spectacular',
    'drf_spectacular_sidecar',
]

if not DEBUG:
    # cache SQL queries in non-debug mode
    INSTALLED_APPS.append('cachalot')

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.cache.UpdateCacheMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.cache.FetchFromCacheMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

PREFIX = os.getenv("URL_PREFIX", "")
URL_PREFIX = f"{PREFIX}"[1:]

ROOT_URLCONF = 'bublik.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BUBLIK_UI_STATIC],
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

MANAGEMENT_COMMANDS_LOG = os.getenv("MANAGEMENT_COMMANDS_LOG")

WSGI_APPLICATION = 'bublik.wsgi.application'
DJANGO_LOG_LEVEL = os.getenv('DJANGO_LOG_LEVEL', 'INFO')
CELERY_LOG_LEVEL = os.getenv('CELERYD_LOG_LEVEL', 'INFO')
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'detailed': {'format': '[%(asctime)s][%(levelname)s](%(module)s) %(message)s'},
        'simple': {'format': '[%(asctime)s][%(levelname)s] %(message)s'},
        'json': {
            'format': '%(asctime)s %(levelname)s %(module)s %(message)s',
            'class': 'pythonjsonlogger.jsonlogger.JsonFormatter',
        },
    },
    'handlers': {
        'command.console': {
            'level': 'DEBUG' if DEBUG else 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'detailed',
        },
        'console': {
            'level': 'DEBUG' if DEBUG else 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file.debug': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(BASE_DIR, 'logs/debug.log'),
            'maxBytes': 15728640,  # 1024 * 1024 * 15B = 15MB
            'backupCount': 10,
            'formatter': 'detailed',
        },
    },
    'loggers': {
        '': {
            'handlers': ['console'],
            'level': DJANGO_LOG_LEVEL,
        },
        'bublik.server': {
            'handlers': ['command.console'],
            'level': DJANGO_LOG_LEVEL,
            'propagate': False,
        },
        'bublik.server.debug': {
            'handlers': ['file.debug'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'celery.task': {
            'handlers': [],
            'level': CELERY_LOG_LEVEL,
            'propagate': True,
            'colorise': True,
        },
    },
}


# Database
# https://docs.djangoproject.com/en/1.11/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': os.getenv('DB_NAME', 'bublik'),
        'USER': os.getenv('DB_USER', 'bublik'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'bublik'),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}


CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        # 'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
        # 'LOCATION': '127.0.0.1:11211',
        # 'TIMEOUT': 60 * 20,
    },
    'run': {
        'BACKEND': 'redis_cache.RedisCache',
        'LOCATION': f'{os.getenv("REDIS_HOST", "redis")}:6379',
        'OPTIONS': {
            'DB': 0,
            'COMPRESSOR_CLASS': 'redis_cache.compressors.BZip2Compressor',
            'COMPRESSOR_CLASS_KWARGS': {
                # 1 - 9; 1 - fastest, biggest; 9 - slowest, smallest
                'compresslevel': 9,
            },
        },
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# Password validation
# https://docs.djangoproject.com/en/1.11/ref/settings/#auth-password-validators

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
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ),
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_FILTER_BACKENDS': ('bublik.core.filter_backends.AllDjangoFilterBackend',),
    'DEFAULT_PAGINATION_CLASS': 'bublik.core.pagination.DefaultPageNumberPagination',
    'EXCEPTION_HANDLER': 'bublik.core.exceptions.custom_exception_handler',
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Bublik API',
    'DESCRIPTION': 'Bublik API documentation',
    'VERSION': '0.6.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SWAGGER_UI_DIST': 'SIDECAR',  # shorthand to use the sidecar instead
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',
}

# Internationalization
# https://docs.djangoproject.com/en/1.11/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.11/howto/static-files/

STATIC_URL = f'{URL_PREFIX}/static/'
if BUBLIK_WEB_STATIC:
    STATIC_ROOT = os.path.join(BUBLIK_WEB_STATIC, 'static/')
else:
    STATIC_ROOT = 'bublik/representation/static/'


def show_toolbar(_):
    return bool(DEBUG)


if DEBUG:
    INSTALLED_APPS.append('debug_toolbar')
    # NOTE: any middleware that encodes the response must come before the debug_toolbar one
    MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')

    DEBUG_TOOLBAR_CONFIG = {
        # force the debug toolbar to rely on our version of jquery
        'JQUERY_URL': '',
        # always show the debug toolbar in debug mode
        'SHOW_TOOLBAR_CALLBACK': 'bublik.settings.show_toolbar',
    }

    # deactivate caching in debug mode
    if CACHES:
        for k in CACHES.keys():
            CACHES[k]['BACKEND'] = 'django.core.cache.backends.dummy.DummyCache'


CELERY_APP = os.getenv("CELERY_APP", "bublik.interfaces")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "amqp://rabbitmq")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "rpc://")
CELERY_ACCEPT_CONTENT = [os.getenv("CELERY_ACCEPT_CONTENT", 'application/json')]
CELERY_TASK_SERIALIZER = os.getenv("CELERY_TASK_SERIALIZER", "json")
CELERY_RESULT_SERIALIZER = os.getenv("CELERY_RESULT_SERIALIZER", "json")
CELERY_CREATE_DIRS = os.getenv("CELERY_CREATE_DIRS", "1")

ENABLE_JSON_LOGS_PROXY = os.getenv("ENABLE_JSON_LOGS_PROXY", False)
SECURE_HTTP = os.getenv("SECURE_HTTP", False)

# Identify a project holding Bublik:
# - to use per-project variables just doing 'import per_conf'
# - to get per-project conf files
#
PER_CONF_DIR = os.getenv("PER_CONF_DIR", "/app/bublik-conf")


def get_module(name, location):
    if not os.path.isfile(location):
        raise FileNotFoundError(f'unable to get {location}')
    spec = importlib.util.spec_from_file_location(name, location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module


get_module('per_conf', f"{PER_CONF_DIR}/per_conf.py")
get_module('references', f"{PER_CONF_DIR}/references.py")

import per_conf

URL_PREFIX_BY_UI_VERSION = {
    1: 'v1',
    2: 'v2',
}

UI_VERSION = getattr(per_conf, 'UI_VERSION', 2)

UI_PREFIX = URL_PREFIX_BY_UI_VERSION.get(UI_VERSION, '')

CSRF_TRUSTED_ORIGINS = getattr(per_conf, 'CSRF_TRUSTED_ORIGINS', [])

ITEMS_PER_PAGE = 25

DATETIME_FORMATS = {
    'db': {
        'default': '%Y.%m.%d %H:%M:%S.%f',
        'iso_date': '%Y-%m-%d',
    },
    'display': {
        'to_date_in_numbers': '%Y-%m-%d',
        'to_date_in_words': '%b %d, %Y',
        'to_seconds': '%b %d %Y, %H:%M:%S',
        'to_microseconds': '%b %d %Y, %H:%M:%S.%f',
    },
    'input': {
        'date': ['%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'],
    },
}

# Delimiters
HASH_FIELD_DELIMITER = b'%'
QUERY_DELIMITER = ';'
KEY_VALUE_DELIMITER = '='
PERIOD_DELIMITER = '-'
TIMESTAMP_DELIMITER = 's'

# Email settings
EMAIL_HOST = os.getenv("EMAIL_HOST", "mailpit")
EMAIL_PORT = os.getenv("EMAIL_PORT", "1025")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True")
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_TIMEOUT = 60
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_ADMINS = [email.strip() for email in os.getenv("EMAIL_ADMINS", "").split(",") if email]

# Repo revisions
REPO_REVISIONS = {
    'repo_url': 'null',
    'repo_branch': 'null',
    'latest_commit': {
        'commit_date': 'null',
        'commit_rev': 'null',
        'commit_summary': 'null',
    },
    'repo_tag': 'null',
}


REPORT_CONFIG_COMPONENTS = {
    'required_keys': [
        'id',
        'name',
        'description',
        'version',
        'title_content',
        'test_names_order',
        'tests',
    ],
    'required_test_keys': [
        'table_view',
        'chart_view',
        'axis_x',
        'axis_y',
        'sequence_group_arg',
        'percentage_base_value',
        'sequence_name_conversion',
        'not_show_args',
        'records_order',
    ],
    'possible_axis_y_keys': [
        'tool',
        'type',
        'name',
        'keys',
        'aggr',
    ],
}

AUTH_USER_MODEL = 'data.User'

# JWT authentication settings for Django REST
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(weeks=1),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=1),
    'SLIDING_TOKEN_REFRESH_EXPIRATION': True,
    'SLIDING_TOKEN_REFRESH_DELTA': timedelta(minutes=5),
    'AUTH_COOKIE_SECURE': True,
    'AUTH_COOKIE_SAMESITE': 'Strict',
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY
}

# Views loading timeouts
VIEWS_TIMEOUTS = {
    'dashboard': 10,
    'runs_list': 5,
    'runs_charts': 300,
    'history_list_base': 120,
    'history_list_intense': 120,
}
