"""
Core URL Configuration.
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView


def health_check(request):
    """Health check endpoint for deployment."""
    return JsonResponse({'status': 'healthy', 'version': '1.0.0'})


urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),
    
    # Health check
    path('health/', health_check, name='health_check'),
    
    # API
    path('api/', include('api.urls')),
    path('api/', include('notifications.urls')),  # Notification endpoints

    # ----------------------------------------------------------------
    # Inbox extension – isolated endpoints (no existing routes changed)
    # GET  /inbox/conversations/
    # GET  /inbox/conversations/{id}/
    # POST /inbox/conversations/{id}/mark-read/
    # GET  /inbox/conversations/{id}/messages/
    # POST /inbox/messages/
    # WS   /ws/inbox/{tenant_id}/?token=<jwt>
    # ----------------------------------------------------------------
    path('inbox/', include('inbox.urls', namespace='inbox')),

    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

# Serve media files.
# In production behind a reverse proxy (Dokploy/nginx) the proxy handles
# TLS and caching; Daphne just needs to serve the bytes from the volume.
# For large-scale deployments, swap this for S3/Blob storage + CDN.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
