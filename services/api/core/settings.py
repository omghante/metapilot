"""
Django settings for Multi-Tenant SaaS API.

Environment variables:
- SECRET_KEY: Django secret key
- DATABASE_URL: PostgreSQL connection string
- DEBUG: True/False
- ALLOWED_HOSTS: Comma-separated list
- FERNET_KEY: Encryption key for API secrets
- CORS_ALLOWED_ORIGINS: Comma-separated list (optional)
"""
import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Security
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-dev-key-change-in-production')
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]

# Encryption key for tenant secrets (Fernet)
FERNET_KEY = os.getenv('FERNET_KEY', '')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')

# WhatsApp Chatbot Configuration
WA_CHATBOT_ENABLED = os.getenv('WA_CHATBOT_ENABLED', 'True').lower() in ('true', '1', 'yes')
WA_CHATBOT_BOT_NAME = os.getenv('WA_CHATBOT_BOT_NAME', 'WhatsApp Assistant')
WA_CHATBOT_MAX_HISTORY = int(os.getenv('WA_CHATBOT_MAX_HISTORY', 15))
# OpenRouter model to use for text responses.
# stepfun/step-3.5-flash  – 196B MoE, activates 11B/token, 256K context, $0.10/M in
# stepfun/step-3.5-flash:free – same model, free tier (rate-limited)
# Override via env: WA_CHATBOT_TEXT_MODEL=stepfun/step-3.5-flash:free
WA_CHATBOT_TEXT_MODEL = os.getenv('WA_CHATBOT_TEXT_MODEL', 'stepfun/step-3.5-flash')
# OpenRouter model for image/vision analysis (must be vision-capable)
WA_CHATBOT_VISION_MODEL = os.getenv('WA_CHATBOT_VISION_MODEL', 'openai/gpt-4o')
# Message sent when no knowledge context is found for the tenant.
# Override via environment variable WA_CHATBOT_FALLBACK_MESSAGE.
WA_CHATBOT_FALLBACK_MESSAGE = os.getenv(
    'WA_CHATBOT_FALLBACK_MESSAGE',
    'Thank you for your message! We have received your query and our team will get back to you shortly.'
)

# Webhook Configuration
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL', '')

if not FERNET_KEY and not DEBUG:
    raise ValueError('FERNET_KEY environment variable is required in production')

# Application definition
INSTALLED_APPS = [
    'daphne',     # ASGI server - must be before django.contrib.staticfiles
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'drf_spectacular',
    'django_celery_beat',  # Celery Beat scheduler
    
    # Local apps
    'users',
    'tenants',
    'api',
    'messaging',
    'campaigns',
    'billing',
    'analytics',
    'webhooks',
    'templates',  # WhatsApp template management
    'notifications',  # Notification system (added after users to ensure proper migration ordering)
    'scheduler',  # High-performance message scheduler
    'chatbot',    # AI Platform Assistant
    'wa_chatbot',  # WhatsApp AI Chatbot

    # ----------------------------------------------------------------
    # Inbox extension layer (chat inbox – no existing apps modified)
    # ----------------------------------------------------------------
    'channels',   # Django Channels for WebSocket support
    'inbox',      # Real-time chat inbox module
]

# Scheduler Configuration
SCHEDULER_BATCH_SIZE = int(os.getenv('SCHEDULER_BATCH_SIZE', 20))
SCHEDULER_RATE_LIMIT_TOKENS = int(os.getenv('SCHEDULER_RATE_LIMIT_TOKENS', 50))
SCHEDULER_RETRY_DELAYS = [60, 300, 900]  # 1min, 5min, 15min
SERVER_ID = os.getenv('SERVER_ID', 'server_01')

# Meta WhatsApp API Configuration
META_GRAPH_API_VERSION = os.getenv('META_GRAPH_API_VERSION', 'v22.0')

# Celery Configuration
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Kolkata'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes max per task

# Route tasks to separate queues - keeps heartbeat responsive
CELERY_TASK_ROUTES = {
    'scheduler.tasks.scheduler_heartbeat': {'queue': 'scheduler'},
    'scheduler.tasks.cleanup_stale_jobs': {'queue': 'scheduler'},
    'scheduler.tasks.process_scheduler_job': {'queue': 'jobs'},
}

# Default queue for unrouted tasks
CELERY_TASK_DEFAULT_QUEUE = 'celery'

# Celery Beat Schedule (periodic tasks)
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_BEAT_SYNC_EVERY = 1  # Sync every task execution (faster but more DB queries)
CELERY_BEAT_MAX_LOOP_INTERVAL = 1  # Check for new schedules every 1 second


MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # Must be first — before any response-generating middleware
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'tenants.middleware.TenantMiddleware',  # Tenant resolution
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

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

WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application'

# Django Channels – Redis channel layer for WebSocket inbox
# Defaults to in-memory (dev); set CHANNEL_REDIS_URL for Redis (production)
_channel_redis_url = os.getenv('CHANNEL_REDIS_URL', os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/1'))

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [_channel_redis_url],
            'capacity': 1500,
            'expiry': 60,
        },
    }
}

# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases
DATABASE_URL = os.getenv('DATABASE_URL', '')

if DATABASE_URL:
    # Parse DATABASE_URL for production (PostgreSQL)
    import dj_database_url
    DATABASES = {
        'default': dj_database_url.config(default=DATABASE_URL, conn_max_age=600)
    }
else:
    # SQLite for development
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Custom User Model
AUTH_USER_MODEL = 'users.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files (user uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ] if not DEBUG else [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
}

# SimpleJWT Configuration
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    
    'TOKEN_TYPE_CLAIM': 'token_type',
}

# CORS Configuration
_cors_origins = os.getenv('CORS_ALLOWED_ORIGINS', '')
if _cors_origins:
    CORS_ALLOWED_ORIGINS = [origin.strip() for origin in _cors_origins.split(',') if origin.strip()]
else:
    # Default origins for development
    CORS_ALLOWED_ORIGINS = [
        'http://localhost:3000',
        'http://127.0.0.1:3000',
        'http://localhost:5173',  # Vite default
        'http://127.0.0.1:5173',
    ]

CORS_ALLOW_ALL_ORIGINS = DEBUG  # Allow all in development

CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-tenant-id',  # Custom header for tenant selection
]

# DRF Spectacular (API Documentation)
SPECTACULAR_SETTINGS = {
    'TITLE': 'WhatsApp Marketing API',
    'DESCRIPTION': 'Multi-Tenant SaaS API for WhatsApp Marketing',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SECURITY': [
        {'BearerAuth': []},
    ],
    'SWAGGER_UI_SETTINGS': {
        'persistAuthorization': True,
    },
}

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose' if not DEBUG else 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}

# =============================================================================
# Production Security Settings
# Dokploy / any reverse-proxy deployment: traffic arrives over HTTPS at the
# proxy and is forwarded to Daphne as plain HTTP — Django must be told to
# trust the X-Forwarded-Proto header so HTTPS-only cookies / redirects work.
# =============================================================================

# Trust the X-Forwarded-Proto header set by Dokploy / nginx reverse proxy
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Only send session & CSRF cookies over HTTPS in production
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# Browser security headers (safe in all environments)
SECURE_BROWSER_XSS_FILTER = True       # Sets X-XSS-Protection: 1; mode=block
SECURE_CONTENT_TYPE_NOSNIFF = True     # Sets X-Content-Type-Options: nosniff
X_FRAME_OPTIONS = 'DENY'              # Prevents clickjacking

# HSTS — only activate in production (never in DEBUG=True local dev)
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000          # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Keep DB connections alive between requests; Daphne is long-lived so this
# avoids a new DB connect on every request.
if DATABASE_URL:
    DATABASES['default']['CONN_MAX_AGE'] = 600
    DATABASES['default']['CONN_HEALTH_CHECKS'] = True

