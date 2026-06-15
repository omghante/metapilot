"""
Notification ViewSet for API endpoints.
Role-based filtering implemented in get_queryset().
"""
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from .models import Notification
from .serializers import NotificationSerializer, NotificationListSerializer, MarkReadSerializer


@extend_schema(
    parameters=[
        OpenApiParameter(name='id', type=OpenApiTypes.UUID, location=OpenApiParameter.PATH, description='Notification UUID')
    ]
)
class NotificationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing notifications.
    
    Endpoints:
    - GET /api/notifications/ - List notifications (filtered by role)
    - GET /api/notifications/{id}/ - Retrieve single notification
    - GET /api/notifications/unread-count/ - Get unread notification count
    - PUT /api/notifications/{id}/mark-read/ - Mark notification as read
    - POST /api/notifications/mark-all-read/ - Mark all notifications as read
    - DELETE /api/notifications/{id}/ - Delete notification
    """
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Filter notifications based on user role.
        Uses indexed ForeignKey fields for fast queries.
        
        - Super Admin: All SUPER_ADMIN role notifications
        - Agency Admin: Notifications for their agency (via agency FK)
        - Client Admin/User: Notifications for their tenant (via tenant FK)
        """
        user = self.request.user
        
        # Base queryset with select_related for optimization
        base_qs = Notification.objects.select_related('user', 'agency', 'tenant')
        
        # Super Admin: See all SUPER_ADMIN notifications
        if user.is_super_admin:
            return base_qs.filter(
                Q(user__role='SUPER_ADMIN') | Q(user=user)
            )
        
        # Agency Admin: See notifications for their agency (fast indexed query)
        elif user.is_agency_admin and user.agency:
            return base_qs.filter(
                Q(user=user) | Q(agency=user.agency)
            )
        
        # Tenant Admin/User: See notifications for their tenant (fast indexed query)
        elif user.tenant:
            return base_qs.filter(
                Q(user=user) | Q(tenant=user.tenant)
            )
        
        # Fallback: Only personal notifications
        return base_qs.filter(user=user)
    
    def get_serializer_class(self):
        """Use optimized serializer for list view."""
        if self.action == 'list':
            return NotificationListSerializer
        return NotificationSerializer
    
    def list(self, request, *args, **kwargs):
        """
        List notifications with optional filtering.
        
        Query params:
        - is_read: Filter by read status (true/false)
        - notification_type: Filter by notification type
        - priority: Filter by priority level
        """
        queryset = self.get_queryset()
        
        # Apply filters
        is_read = request.query_params.get('is_read')
        if is_read is not None:
            is_read_bool = is_read.lower() in ('true', '1', 'yes')
            queryset = queryset.filter(is_read=is_read_bool)
        
        notification_type = request.query_params.get('notification_type')
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)
        
        priority = request.query_params.get('priority')
        if priority:
            queryset = queryset.filter(priority=priority)
        
        # Paginate and serialize
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        """Get count of unread notifications for current user."""
        count = self.get_queryset().filter(is_read=False).count()
        return Response({'count': count})
    
    @action(detail=True, methods=['put'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        """Mark a single notification as read."""
        notification = self.get_object()
        
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=['is_read', 'read_at'])
        
        serializer = self.get_serializer(notification)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        """Mark all unread notifications as read."""
        queryset = self.get_queryset().filter(is_read=False)
        updated_count = queryset.update(
            is_read=True,
            read_at=timezone.now()
        )
        
        return Response({
            'message': f'{updated_count} notification(s) marked as read',
            'count': updated_count
        })
    
    def destroy(self, request, *args, **kwargs):
        """Delete a notification."""
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {'message': 'Notification deleted successfully'},
            status=status.HTTP_204_NO_CONTENT
        )
