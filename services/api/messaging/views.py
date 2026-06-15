"""
Messaging views for WhatsApp contact and message management.
All endpoints are tenant-scoped.
"""
import logging
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from api.permissions import IsTenantMember, TenantAccessPermission, IsTenantMemberOrAgencyAdmin, AgencyTenantAccessPermission
from messaging.models import (
    Contact, Conversation, Message,
    MessageDirection, MessageStatus, MessageType, ConversationStatus
)
from messaging.serializers import (
    ContactSerializer, ContactCreateSerializer,
    ConversationSerializer, ConversationDetailSerializer,
    MessageSerializer, MessageSendSerializer
)
from users.models import UserRole

logger = logging.getLogger(__name__)


class ContactViewSet(viewsets.ModelViewSet):
    """
    ViewSet for contact management.
    
    🟢 TENANT MEMBERS
    🟡 AGENCY ADMINS (can manage contacts for their client tenants)
    
    Endpoints:
    - GET /api/contacts/ - List tenant's contacts
    - GET /api/contacts/?tenant_id={id} - List contacts for specific tenant (agency admins)
    - GET /api/contacts/?search=query - Search contacts by name, phone, or email
    - POST /api/contacts/ - Create new contact
    - GET /api/contacts/{id}/ - Get contact details
    - PUT/PATCH /api/contacts/{id}/ - Update contact
    - DELETE /api/contacts/{id}/ - Delete contact
    """
    permission_classes = [IsTenantMemberOrAgencyAdmin, AgencyTenantAccessPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'phone', 'email']
    
    def get_queryset(self):
        user = self.request.user
        tenant_id = self.request.query_params.get('tenant_id')
        
        # Base queryset with optimized joins
        base_qs = Contact.objects.select_related('tenant')
        
        # Super admin can see all or filter by tenant_id
        if user.is_super_admin:
            if tenant_id:
                return base_qs.filter(tenant_id=tenant_id)
            return base_qs.all()
        
        # Agency admin can access their clients' contacts
        if user.role == UserRole.AGENCY_ADMIN and user.agency:
            if tenant_id:
                from tenants.models import Tenant
                if Tenant.objects.filter(id=tenant_id, agency=user.agency).exists():
                    return base_qs.filter(tenant_id=tenant_id)
                return Contact.objects.none()
            # Return all contacts for all tenants under agency
            return base_qs.filter(tenant__agency=user.agency)
        
        # Tenant members see their own
        return base_qs.filter(tenant=user.tenant)
    
    def get_serializer_class(self):
        if self.action == 'create':
            return ContactCreateSerializer
        return ContactSerializer
    
    def perform_create(self, serializer):
        user = self.request.user
        tenant_id = self.request.data.get('tenant_id') or self.request.query_params.get('tenant_id')
        
        # Agency admin creating contact for a client
        if user.role == UserRole.AGENCY_ADMIN and tenant_id and user.agency:
            from tenants.models import Tenant
            tenant = Tenant.objects.filter(id=tenant_id, agency=user.agency).first()
            if tenant:
                serializer.save(tenant=tenant)
                return
        
        # Default: use user's tenant
        serializer.save(tenant=self.request.user.tenant)
    
    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        """
        Bulk delete contacts by IDs.
        
        POST /api/contacts/bulk-delete/
        Body: {"ids": ["uuid1", "uuid2", ...]}
        
        Only deletes contacts that belong to the user's tenant (or agency's tenants).
        """
        ids = request.data.get('ids', [])
        if not ids or not isinstance(ids, list):
            return Response(
                {'error': 'Please provide a list of contact IDs in the "ids" field.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Use the existing get_queryset which already handles tenant scoping
        queryset = self.get_queryset().filter(id__in=ids)
        count = queryset.count()
        queryset.delete()
        
        # Audit log
        logger.info(
            "Bulk contact delete",
            extra={
                "action": "bulk_delete_contacts",
                "user_id": str(request.user.id),
                "user_email": request.user.email,
                "tenant_id": str(getattr(request.user, 'tenant_id', None)),
                "requested_count": len(ids),
                "deleted_count": count,
            }
        )
        
        return Response({
            'message': f'{count} contact(s) deleted successfully.',
            'deleted_count': count,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def block(self, request, pk=None):
        """Block a contact from receiving messages."""
        contact = self.get_object()
        contact.is_blocked = True
        contact.save()
        return Response({'message': f'Contact {contact.phone} blocked'})
    
    @action(detail=True, methods=['post'])
    def unblock(self, request, pk=None):
        """Unblock a contact."""
        contact = self.get_object()
        contact.is_blocked = False
        contact.save()
        return Response({'message': f'Contact {contact.phone} unblocked'})


class ConversationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for conversation management.
    
    🟢 TENANT MEMBERS
    
    Endpoints:
    - GET /api/conversations/ - List tenant's conversations
    - GET /api/conversations/{id}/ - Get conversation with messages
    - POST /api/conversations/{id}/archive/ - Archive conversation
    """
    permission_classes = [IsTenantMember, TenantAccessPermission]
    http_method_names = ['get', 'patch', 'delete']  # No direct create
    
    def get_queryset(self):
        user = self.request.user
        if user.is_super_admin:
            return Conversation.objects.select_related('contact').all()
        return Conversation.objects.select_related('contact').filter(
            contact__tenant=user.tenant
        )
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ConversationDetailSerializer
        return ConversationSerializer
    
    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive a conversation."""
        conversation = self.get_object()
        conversation.status = ConversationStatus.ARCHIVED
        conversation.save()
        return Response({'message': 'Conversation archived'})
    
    @action(detail=True, methods=['post'])
    def unarchive(self, request, pk=None):
        """Unarchive a conversation."""
        conversation = self.get_object()
        conversation.status = ConversationStatus.ACTIVE
        conversation.save()
        return Response({'message': 'Conversation unarchived'})


class MessageViewSet(viewsets.ModelViewSet):
    """
    ViewSet for message management.
    
    🟢 TENANT MEMBERS
    
    Endpoints:
    - GET /api/messages/ - List messages (filter by conversation_id)
    - POST /api/messages/send/ - Send a new message
    """
    permission_classes = [IsTenantMember, TenantAccessPermission]
    serializer_class = MessageSerializer
    http_method_names = ['get', 'post']
    
    def get_queryset(self):
        user = self.request.user
        queryset = Message.objects.select_related(
            'conversation', 'conversation__contact'
        )
        
        if not user.is_super_admin:
            queryset = queryset.filter(
                conversation__contact__tenant=user.tenant
            )
        
        # Filter by conversation if provided
        conversation_id = self.request.query_params.get('conversation_id')
        if conversation_id:
            queryset = queryset.filter(conversation_id=conversation_id)
        
        return queryset
    
    @action(detail=False, methods=['post'])
    def send(self, request):
        """
        Send a new WhatsApp message.
        
        POST /api/messages/send/
        
        Body:
        - contact_id or phone (required)
        - message_type: TEXT, TEMPLATE, IMAGE, DOCUMENT
        - content: message text (for TEXT)
        - template_name: template name (for TEMPLATE)
        - template_params: template parameters
        - media_url: URL for media messages
        """
        serializer = MessageSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        
        tenant = request.user.tenant
        if not tenant:
            return Response(
                {'error': 'No tenant associated with user'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check quota before sending
        from analytics.models import ClientQuota
        quota, created = ClientQuota.objects.get_or_create(
            tenant=tenant,
            defaults={
                'daily_message_limit': 100,
                'monthly_message_limit': 1000
            }
        )
        
        if not quota.can_send_message():
            remaining_daily = max(0, quota.daily_message_limit - quota.messages_sent_today)
            remaining_monthly = max(0, quota.monthly_message_limit - quota.messages_sent_this_month)
            return Response({
                'error': 'Message limit exceeded',
                'details': {
                    'daily_limit': quota.daily_message_limit,
                    'monthly_limit': quota.monthly_message_limit,
                    'daily_used': quota.messages_sent_today,
                    'monthly_used': quota.messages_sent_this_month,
                    'remaining_daily': remaining_daily,
                    'remaining_monthly': remaining_monthly
                }
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        # Get or create contact
        if data.get('contact_id'):
            try:
                contact = Contact.objects.get(
                    id=data['contact_id'],
                    tenant=tenant
                )
            except Contact.DoesNotExist:
                return Response(
                    {'error': 'Contact not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            phone = data['phone']
            contact, created = Contact.objects.get_or_create(
                tenant=tenant,
                phone=phone,
                defaults={'name': ''}
            )
        
        # Get or create conversation
        conversation, created = Conversation.objects.get_or_create(
            contact=contact,
            defaults={'status': ConversationStatus.ACTIVE}
        )
        
        # Create message record
        message = Message.objects.create(
            conversation=conversation,
            direction=MessageDirection.OUTBOUND,
            message_type=data.get('message_type', 'TEXT'),
            status=MessageStatus.PENDING,
            content=data.get('content', ''),
            payload={
                'template_name': data.get('template_name'),
                'template_params': data.get('template_params', []),
                'header_image': data.get('header_image'),
                'button_params': data.get('button_params', []),
            },
            media_url=data.get('media_url', '')
        )
        
        # Increment quota usage after successful message creation
        quota.increment_usage()
        
        # Update conversation last_message_at
        conversation.last_message_at = timezone.now()
        conversation.save()
        
        # Send message via WhatsApp API
        from messaging.whatsapp_service import send_message
        send_success = send_message(message)
        
        # Refresh message to get updated status
        message.refresh_from_db()
        
        return Response({
            'message': 'Message sent' if send_success else 'Message send failed',
            'success': send_success,
            'data': MessageSerializer(message).data,
            'quota': {
                'daily_remaining': quota.daily_message_limit - quota.messages_sent_today,
                'monthly_remaining': quota.monthly_message_limit - quota.messages_sent_this_month
            }
        }, status=status.HTTP_201_CREATED if send_success else status.HTTP_200_OK)


class ContactImportView(APIView):
    """
    Import contacts from CSV/XLSX file.
    
    POST /api/contacts/import/
    
    🟢 TENANT MEMBERS
    🟡 AGENCY ADMINS (can import for their client tenants)
    
    Accepts multipart/form-data with:
    - file: CSV or XLSX file
    - tags: Optional tags to apply (JSON array as string)
    - tenant_id: Optional tenant to import for (agency admins)
    
    Required columns: phone
    Optional columns: name, email, tags
    """
    permission_classes = [IsTenantMemberOrAgencyAdmin, AgencyTenantAccessPermission]
    
    def post(self, request):
        from messaging.models import ContactImport, ContactImportStatus
        import io
        
        user = request.user
        tenant_id = request.data.get('tenant_id') or request.query_params.get('tenant_id')
        
        # Determine tenant
        if user.role == UserRole.AGENCY_ADMIN and tenant_id and user.agency:
            from tenants.models import Tenant
            tenant = Tenant.objects.filter(id=tenant_id, agency=user.agency).first()
            if not tenant:
                return Response(
                    {'error': 'Tenant not found or not authorized'},
                    status=status.HTTP_403_FORBIDDEN
                )
        else:
            tenant = user.tenant
        
        if not tenant:
            return Response(
                {'error': 'No tenant associated with user'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get uploaded file
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response(
                {'error': 'No file provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check file type
        file_name = uploaded_file.name.lower()
        if file_name.endswith('.csv'):
            file_type = 'csv'
        elif file_name.endswith('.xlsx') or file_name.endswith('.xls'):
            file_type = 'xlsx'
        else:
            return Response(
                {'error': 'Invalid file type. Supported: CSV, XLSX'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get optional tags
        apply_tags = []
        tags_str = request.data.get('tags', '[]')
        try:
            import json
            apply_tags = json.loads(tags_str) if isinstance(tags_str, str) else tags_str
        except:
            pass
        
        # Get optional name for the import
        import_name = request.data.get('name', '').strip()
        
        # Create import record
        contact_import = ContactImport.objects.create(
            tenant=tenant,
            uploaded_by=request.user,
            name=import_name,
            file_name=uploaded_file.name,
            file_type=file_type,
            apply_tags=apply_tags,
            status=ContactImportStatus.PROCESSING
        )
        contact_import.started_at = timezone.now()
        contact_import.save()
        
        # Process file
        try:
            import pandas as pd
            
            if file_type == 'csv':
                df = pd.read_csv(io.BytesIO(uploaded_file.read()))
            else:
                df = pd.read_excel(io.BytesIO(uploaded_file.read()))
            
            # Validate columns
            if 'phone' not in df.columns:
                contact_import.status = ContactImportStatus.FAILED
                contact_import.errors = [{'error': 'Missing required column: phone'}]
                contact_import.save()
                return Response(
                    {'error': 'Missing required column: phone'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            contact_import.total_rows = len(df)
            imported = 0
            updated = 0
            errors = []
            
            for idx, row in df.iterrows():
                try:
                    phone = str(row['phone']).strip()
                    if not phone or phone == 'nan':
                        errors.append({'row': idx + 2, 'error': 'Empty phone number'})
                        continue
                    
                    name = str(row.get('name', '')).strip() if 'name' in df.columns else ''
                    email = str(row.get('email', '')).strip() if 'email' in df.columns else ''
                    
                    # Handle row-level tags
                    row_tags = []
                    if 'tags' in df.columns:
                        tag_value = row.get('tags', '')
                        if isinstance(tag_value, str) and tag_value:
                            row_tags = [t.strip() for t in tag_value.split(',')]
                    
                    # Combine with import-level tags
                    all_tags = list(set(apply_tags + row_tags))
                    
                    # Try to get existing contact
                    existing_contact = Contact.objects.filter(
                        tenant=tenant,
                        phone=phone
                    ).first()
                    
                    if existing_contact:
                        # Update existing contact with new data (don't skip!)
                        if name and name != 'nan':
                            existing_contact.name = name
                        if email and email != 'nan':
                            existing_contact.email = email
                        if all_tags:
                            existing_tags = existing_contact.tags or []
                            existing_contact.tags = list(set(existing_tags + all_tags))
                        existing_contact.is_subscribed = True  # Re-subscribe if already exists
                        # NOTE: Do NOT overwrite import_source on existing contacts.
                        # This prevents data loss when deleting an import batch.
                        existing_contact.save()
                        updated += 1
                    else:
                        # Create new contact
                        Contact.objects.create(
                            tenant=tenant,
                            phone=phone,
                            name=name if name != 'nan' else '',
                            email=email if email != 'nan' else None,
                            tags=all_tags,
                            is_subscribed=True,
                            import_source=contact_import,  # Track import source
                        )
                        imported += 1
                
                except Exception as e:
                    errors.append({'row': idx + 2, 'error': str(e)})
            
            # Update import record
            contact_import.imported_count = imported
            contact_import.duplicate_count = updated  # Now represents "updated" contacts
            contact_import.error_count = len(errors)
            contact_import.errors = errors[:100]  # Limit stored errors
            contact_import.status = ContactImportStatus.COMPLETED
            contact_import.completed_at = timezone.now()
            contact_import.save()
            
            return Response({
                'message': 'Import completed',
                'import_id': str(contact_import.id),
                'total_rows': contact_import.total_rows,
                'imported': imported,
                'updated': updated,
                'errors': len(errors)
            })
        
        except Exception as e:
            contact_import.status = ContactImportStatus.FAILED
            contact_import.errors = [{'error': str(e)}]
            contact_import.save()
            return Response(
                {'error': f'Import failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class MediaAssetViewSet(viewsets.ModelViewSet):
    """
    ViewSet for media asset management (templates, banners).
    
    🟢 TENANT MEMBERS
    🟡 AGENCY ADMINS (can manage media for their client tenants)
    
    Endpoints:
    - GET /api/media/ - List tenant's media assets
    - GET /api/media/?tenant_id={id} - List media for specific tenant (agency admins)
    - POST /api/media/ - Upload new media
    - GET /api/media/{id}/ - Get media details
    - DELETE /api/media/{id}/ - Delete media
    """
    permission_classes = [IsTenantMemberOrAgencyAdmin, AgencyTenantAccessPermission]
    
    def get_queryset(self):
        from messaging.models import MediaAsset
        user = self.request.user
        tenant_id = self.request.query_params.get('tenant_id')
        
        # Base queryset with optimized joins
        base_qs = MediaAsset.objects.select_related('tenant', 'uploaded_by')
        
        # Super admin can see all or filter by tenant_id
        if user.is_super_admin:
            if tenant_id:
                return base_qs.filter(tenant_id=tenant_id)
            return base_qs.all()
        
        # Agency admin can access their clients' media
        if user.role == UserRole.AGENCY_ADMIN and user.agency:
            if tenant_id:
                from tenants.models import Tenant
                if Tenant.objects.filter(id=tenant_id, agency=user.agency).exists():
                    return base_qs.filter(tenant_id=tenant_id)
                return MediaAsset.objects.none()
            # Return all media for all tenants under agency
            return base_qs.filter(tenant__agency=user.agency)
        
        # Tenant members see their own
        return base_qs.filter(tenant=user.tenant)
    
    def get_serializer_class(self):
        from messaging.serializers import MediaAssetSerializer, MediaAssetCreateSerializer
        if self.action == 'create':
            return MediaAssetCreateSerializer
        return MediaAssetSerializer
    
    def perform_create(self, serializer):
        user = self.request.user
        tenant_id = self.request.data.get('tenant_id') or self.request.query_params.get('tenant_id')
        
        # Agency admin creating media for a client
        if user.role == UserRole.AGENCY_ADMIN and tenant_id and user.agency:
            from tenants.models import Tenant
            tenant = Tenant.objects.filter(id=tenant_id, agency=user.agency).first()
            if tenant:
                serializer.save(tenant=tenant, uploaded_by=user)
                return
        
        # Default: use user's tenant
        serializer.save(
            tenant=self.request.user.tenant,
            uploaded_by=self.request.user
        )
    
    @action(detail=True, methods=['get'], url_path='file',
            permission_classes=[], authentication_classes=[])
    def serve_file(self, request, pk=None):
        """
        Serve media file bytes from PostgreSQL (public with token).
        
        GET /api/media/{id}/file/?token={public_token}
        
        Requires a per-asset token for access control.
        WhatsApp servers use the full URL (including token) to fetch media.
        """
        from django.http import HttpResponse, HttpResponseNotFound, HttpResponseForbidden
        from django.shortcuts import get_object_or_404
        from messaging.models import MediaAsset
        
        asset = get_object_or_404(MediaAsset, pk=pk, is_active=True)
        
        # Validate per-asset token
        token = request.GET.get('token', '')
        if not asset.public_token or token != asset.public_token:
            return HttpResponseForbidden('Invalid or missing token')
        
        if not asset.file_data:
            return HttpResponseNotFound('File not found')
        
        response = HttpResponse(
            bytes(asset.file_data),
            content_type=asset.content_type or 'application/octet-stream'
        )
        response['Cache-Control'] = 'public, max-age=86400'  # 24 hours
        response['Content-Length'] = len(asset.file_data)
        return response


class ContactImportViewSet(viewsets.ModelViewSet):
    """
    ViewSet for contact import management.
    
    🟢 TENANT MEMBERS
    🟡 AGENCY ADMINS (can manage imports for their client tenants)
    
    Endpoints:
    - GET /api/contact-imports/ - List tenant's contact imports
    - GET /api/contact-imports/?tenant_id={id} - List imports for specific tenant (agency admins)
    - GET /api/contact-imports/{id}/ - Get import details
    - DELETE /api/contact-imports/{id}/ - Delete import record
    - DELETE /api/contact-imports/{id}/?delete_contacts=true - Delete import and associated contacts
    """
    permission_classes = [IsTenantMemberOrAgencyAdmin, AgencyTenantAccessPermission]
    http_method_names = ['get', 'delete']
    
    def get_queryset(self):
        from messaging.models import ContactImport
        user = self.request.user
        tenant_id = self.request.query_params.get('tenant_id')
        
        # Base queryset with optimized joins
        base_qs = ContactImport.objects.select_related('tenant', 'uploaded_by')
        
        # Super admin can see all or filter by tenant_id
        if user.is_super_admin:
            if tenant_id:
                return base_qs.filter(tenant_id=tenant_id)
            return base_qs.all()
        
        # Agency admin can access their clients' imports
        if user.role == UserRole.AGENCY_ADMIN and user.agency:
            if tenant_id:
                from tenants.models import Tenant
                if Tenant.objects.filter(id=tenant_id, agency=user.agency).exists():
                    return base_qs.filter(tenant_id=tenant_id)
                return ContactImport.objects.none()
            # Return all imports for all tenants under agency
            return base_qs.filter(tenant__agency=user.agency)
        
        # Tenant members see their own
        return base_qs.filter(tenant=user.tenant)
    
    def get_serializer_class(self):
        from messaging.serializers import ContactImportSerializer
        return ContactImportSerializer
    
    def destroy(self, request, *args, **kwargs):
        """
        Delete a contact import record.
        
        Query params:
        - delete_contacts: If 'true', also delete all contacts that were imported with this file
        """
        instance = self.get_object()
        delete_contacts = request.query_params.get('delete_contacts', '').lower() == 'true'
        
        deleted_contacts_count = 0
        if delete_contacts:
            # Delete all contacts that were imported via this batch
            contacts_qs = Contact.objects.filter(import_source=instance)
            deleted_contacts_count = contacts_qs.count()
            contacts_qs.delete()
        
        import_id = str(instance.id)
        file_name = instance.file_name
        instance.delete()
        
        return Response({
            'message': f'Import record "{file_name}" deleted successfully',
            'import_id': import_id,
            'contacts_deleted': deleted_contacts_count
        }, status=status.HTTP_200_OK)


