"""
API URL Configuration.
All API endpoints are prefixed with /api/
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from api.views.auth import LoginView, RegisterView, MeView, RefreshTokenView, LogoutView, MyTenantView
from api.views.agencies import AgencyViewSet
from api.views.tenants import TenantViewSet
from api.views.users import UserViewSet
from api.views.config import TenantConfigViewSet
from api.views.dashboard import DashboardOverviewView, AuditLogListView, DashboardAnalyticsView
from api.views.tenant_dashboard import MyDashboardView
from api.views.setup import CreateSuperAdminView, SetupStatusView
from api.views.agency_dashboard import (
    AgencyDashboardView, AgencyClientsListView, AgencyClientDetailView,
    AgencyClientSuspendView, AgencyClientActivateView
)
from messaging.views import (
    ContactViewSet, ConversationViewSet, MessageViewSet,
    ContactImportView, MediaAssetViewSet, ContactImportViewSet
)
from campaigns.views import CampaignViewSet, CampaignMessageViewSet
from webhooks.views import WebhookVerifyView, WebhookReceiveView
from analytics.views import ClientQuotaViewSet, ClientQuotaByTenantView
from templates.views import (
    ClientTemplateListView, TemplateLibraryView,
    TemplateLibrarySyncView, WhatsAppBusinessProfileView,
    MetaTemplateCreateView, MetaTemplateStatusView, MetaTemplateDeleteView
)
from api.views.health import HealthCheckViewSet
from scheduler.views import SchedulerJobViewSet
from messaging.universal_send import universal_send

# Create router for ViewSets
router = DefaultRouter()
router.register(r'agencies', AgencyViewSet, basename='agency')
router.register(r'clients', TenantViewSet, basename='client')
router.register(r'users', UserViewSet, basename='user')
router.register(r'configs', TenantConfigViewSet, basename='config')
router.register(r'contacts', ContactViewSet, basename='contact')
router.register(r'conversations', ConversationViewSet, basename='conversation')
router.register(r'messages', MessageViewSet, basename='message')
router.register(r'campaigns', CampaignViewSet, basename='campaign')
router.register(r'media', MediaAssetViewSet, basename='media')
router.register(r'contact-imports', ContactImportViewSet, basename='contact-import')
router.register(r'quotas', ClientQuotaViewSet, basename='quota')
router.register(r'scheduler/jobs', SchedulerJobViewSet, basename='scheduler-job')
router.register(r'requirements', HealthCheckViewSet, basename='requirements')

# Nested route patterns for campaign messages
campaign_message_patterns = [
    path('campaigns/<uuid:campaign_pk>/messages/', 
         CampaignMessageViewSet.as_view({'get': 'list', 'post': 'create'}), 
         name='campaign-messages-list'),
    path('campaigns/<uuid:campaign_pk>/messages/<uuid:pk>/', 
         CampaignMessageViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'}), 
         name='campaign-messages-detail'),
    path('campaigns/<uuid:campaign_pk>/messages/<uuid:pk>/recipients/', 
         CampaignMessageViewSet.as_view({'get': 'recipients'}), 
         name='campaign-messages-recipients'),
]

# Auth URLs
auth_urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('register/', RegisterView.as_view(), name='register'),
    path('me/', MeView.as_view(), name='me'),
    path('my-tenant/', MyTenantView.as_view(), name='my-tenant'),
    path('refresh/', RefreshTokenView.as_view(), name='token_refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
]

# Setup URLs (for initial configuration without Shell)
setup_urlpatterns = [
    path('status/', SetupStatusView.as_view(), name='setup-status'),
    path('create-superadmin/', CreateSuperAdminView.as_view(), name='create-superadmin'),
]

# Agency Dashboard URLs (for Agency Admins)
agency_urlpatterns = [
    path('dashboard/', AgencyDashboardView.as_view(), name='agency-dashboard'),
    path('clients/', AgencyClientsListView.as_view(), name='agency-clients'),
    path('clients/<uuid:client_id>/', AgencyClientDetailView.as_view(), name='agency-client-detail'),
    path('clients/<uuid:client_id>/suspend/', AgencyClientSuspendView.as_view(), name='agency-client-suspend'),
    path('clients/<uuid:client_id>/activate/', AgencyClientActivateView.as_view(), name='agency-client-activate'),
]

# Webhook URLs (public, for Meta WhatsApp)
webhook_urlpatterns = [
    path('verify/', WebhookVerifyView.as_view(), name='webhook-verify'),
    path('receive/', WebhookReceiveView.as_view(), name='webhook-receive'),
]

urlpatterns = [
    # Auth
    path('auth/', include((auth_urlpatterns, 'auth'))),
    
    # Setup (one-time)
    path('setup/', include((setup_urlpatterns, 'setup'))),
    
    # Super Admin Dashboard
    path('dashboard/', DashboardOverviewView.as_view(), name='dashboard'),
    path('dashboard/analytics/', DashboardAnalyticsView.as_view(), name='dashboard-analytics'),
    path('audit-logs/', AuditLogListView.as_view(), name='audit-logs'),
    
    # Tenant Dashboard (for Tenant Admins/Users)
    path('my-dashboard/', MyDashboardView.as_view(), name='my-dashboard'),
    
    # Agency Dashboard (for Agency Admins)
    path('agency/', include((agency_urlpatterns, 'agency'))),
    
    # Webhooks (public, no auth)
    path('webhooks/', include((webhook_urlpatterns, 'webhooks'))),
    
    # Contact Import (CSV/XLSX)
    path('contacts/import/', ContactImportView.as_view(), name='contact-import'),
    
    # Client Quota Management (Super Admin & Agency Admin)
    path('clients/<uuid:client_id>/quota/', 
         ClientQuotaByTenantView.as_view({'get': 'retrieve', 'patch': 'partial_update'}), 
         name='client-quota'),
    
    # Client Templates (for campaign creation - TENANT MEMBERS)
    path('templates/client/', ClientTemplateListView.as_view(), name='client-templates'),
    
    # Meta Graph API - Template Library (cached, with filters & counts)
    path('templates/meta/', TemplateLibraryView.as_view(), name='template-library'),
    path('templates/meta/sync/', TemplateLibrarySyncView.as_view(), name='template-library-sync'),
    path('templates/meta/business-profile/', WhatsAppBusinessProfileView.as_view(), name='whatsapp-business-profile'),
    path('templates/meta/create/', MetaTemplateCreateView.as_view(), name='template-create'),
    path('templates/meta/status/<str:template_name>/', MetaTemplateStatusView.as_view(), name='template-status'),
    path('templates/meta/delete/<str:template_name>/', MetaTemplateDeleteView.as_view(), name='template-delete'),
    
    # Universal WhatsApp Template Message Send (TENANT MEMBERS)
    path('messaging/send', universal_send, name='messaging-send'),
    
    # Campaign Messages (nested under campaigns)
    *campaign_message_patterns,
    
    # Router (agencies, clients, users, quotas, contacts, conversations, messages, campaigns, media)
    path('chatbot/', include('chatbot.urls')),
    path('wa-chatbot/', include('wa_chatbot.urls')),
    path('', include(router.urls)),
]




