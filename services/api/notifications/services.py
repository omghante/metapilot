"""
Notification service for creating role-based notifications.
"""
from typing import Optional, List
from django.db.models import Q
from .models import Notification, NotificationType, NotificationPriority


class NotificationService:
    """Service class for creating and managing notifications."""
    
    @staticmethod
    def create_notification(
        user,
        notification_type: str,
        title: str,
        message: str,
        priority: str = NotificationPriority.MEDIUM,
        metadata: Optional[dict] = None,
        action_url: str = '',
        agency=None,
        tenant=None
    ) -> Notification:
        """
        Create a notification for a specific user.
        
        Args:
            user: User instance
            notification_type: Type from NotificationType enum
            title: Notification title
            message: Notification message
            priority: Priority level (default: MEDIUM)
            metadata: Additional data (campaign_id, etc.)
            action_url: Optional URL for action button
            agency: Optional Agency FK for fast indexed queries
            tenant: Optional Tenant FK for fast indexed queries
        
        Returns:
            Created Notification instance
        """
        return Notification.objects.create(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=priority,
            metadata=metadata or {},
            action_url=action_url,
            agency=agency,
            tenant=tenant
        )
    
    @staticmethod
    def notify_super_admins(
        notification_type: str,
        title: str,
        message: str,
        priority: str = NotificationPriority.MEDIUM,
        metadata: Optional[dict] = None,
        action_url: str = ''
    ) -> List[Notification]:
        """
        Create notifications for all super admins.
        
        Returns:
            List of created Notification instances
        """
        from users.models import User, UserRole
        
        super_admins = User.objects.filter(
            role=UserRole.SUPER_ADMIN,
            is_active=True
        )
        
        notifications = []
        for admin in super_admins:
            notification = NotificationService.create_notification(
                user=admin,
                notification_type=notification_type,
                title=title,
                message=message,
                priority=priority,
                metadata=metadata,
                action_url=action_url
            )
            notifications.append(notification)
        
        return notifications
    
    @staticmethod
    def notify_agency_admins(
        agency,
        notification_type: str,
        title: str,
        message: str,
        priority: str = NotificationPriority.MEDIUM,
        metadata: Optional[dict] = None,
        action_url: str = ''
    ) -> List[Notification]:
        """
        Create notifications for all admins of a specific agency.
        
        Args:
            agency: Agency instance
            Other args: Same as create_notification
        
        Returns:
            List of created Notification instances
        """
        from users.models import User, UserRole
        
        agency_admins = User.objects.filter(
            role=UserRole.AGENCY_ADMIN,
            agency=agency,
            is_active=True
        )
        
        # The agency_id is now stored in the indexed `agency` FK field
        notification_metadata = metadata or {}
        
        notifications = []
        for admin in agency_admins:
            notification = NotificationService.create_notification(
                user=admin,
                notification_type=notification_type,
                title=title,
                message=message,
                priority=priority,
                metadata=notification_metadata,
                action_url=action_url,
                agency=agency  # Fast indexed FK
            )
            notifications.append(notification)
        
        return notifications
    
    @staticmethod
    def notify_tenant_admins(
        tenant,
        notification_type: str,
        title: str,
        message: str,
        priority: str = NotificationPriority.MEDIUM,
        metadata: Optional[dict] = None,
        action_url: str = ''
    ) -> List[Notification]:
        """
        Create notifications for all admins of a specific tenant.
        
        Args:
            tenant: Tenant instance
            Other args: Same as create_notification
        
        Returns:
            List of created Notification instances
        """
        from users.models import User, UserRole
        
        tenant_admins = User.objects.filter(
            Q(role=UserRole.TENANT_ADMIN) | Q(role=UserRole.TENANT_USER),
            tenant=tenant,
            is_active=True
        )
        
        # The tenant_id is now stored in the indexed `tenant` FK field
        notification_metadata = metadata or {}
        
        notifications = []
        for admin in tenant_admins:
            notification = NotificationService.create_notification(
                user=admin,
                notification_type=notification_type,
                title=title,
                message=message,
                priority=priority,
                metadata=notification_metadata,
                action_url=action_url,
                tenant=tenant  # Fast indexed FK
            )
            notifications.append(notification)
        
        return notifications
    
    # ============================================
    # Convenience methods for common notifications
    # ============================================
    
    @staticmethod
    def notify_on_user_registration(user):
        """Notify tenant and agency admins when a new user registers."""
        notifications = []
        
        # If user belongs to a tenant, notify tenant admins
        if user.tenant:
            tenant_notifications = NotificationService.notify_tenant_admins(
                tenant=user.tenant,
                notification_type=NotificationType.USER_REGISTERED,
                title='New User Registered',
                message=f'{user.email} ({user.get_role_display()}) has registered',
                priority=NotificationPriority.LOW,
                metadata={
                    'user_id': str(user.id),
                    'role': user.role,
                    'email': user.email
                }
            )
            notifications.extend(tenant_notifications)
            
            # Also notify agency if tenant belongs to one
            if user.tenant.agency:
                agency_notifications = NotificationService.notify_agency_admins(
                    agency=user.tenant.agency,
                    notification_type=NotificationType.USER_REGISTERED,
                    title='New User in Client',
                    message=f'{user.email} registered in {user.tenant.name}',
                    priority=NotificationPriority.LOW,
                    metadata={
                        'user_id': str(user.id),
                        'tenant_id': str(user.tenant.id),
                        'tenant_name': user.tenant.name,
                        'agency_id': str(user.tenant.agency.id)
                    }
                )
                notifications.extend(agency_notifications)
        
        return notifications
    
    @staticmethod
    def notify_on_campaign_completion(campaign):
        """Notify relevant admins when a campaign completes."""
        notifications = []
        
        # Notify tenant admins
        tenant_notifications = NotificationService.notify_tenant_admins(
            tenant=campaign.tenant,
            notification_type=NotificationType.CAMPAIGN_COMPLETED,
            title='Campaign Completed',
            message=f'Campaign "{campaign.name}" has completed successfully',
            priority=NotificationPriority.LOW,
            metadata={
                'campaign_id': str(campaign.id),
                'campaign_name': campaign.name,
                'tenant_id': str(campaign.tenant.id)
            },
            action_url=f'/dashboard/campaigns/{campaign.id}'
        )
        notifications.extend(tenant_notifications)
        
        # Also notify agency admins if agency exists
        if campaign.tenant.agency:
            agency_notifications = NotificationService.notify_agency_admins(
                agency=campaign.tenant.agency,
                notification_type=NotificationType.CAMPAIGN_COMPLETED,
                title='Client Campaign Completed',
                message=f'{campaign.tenant.name}: Campaign "{campaign.name}" completed',
                priority=NotificationPriority.LOW,
                metadata={
                    'campaign_id': str(campaign.id),
                    'campaign_name': campaign.name,
                    'tenant_id': str(campaign.tenant.id),
                    'agency_id': str(campaign.tenant.agency.id)
                },
                action_url=f'/dashboard/campaigns/{campaign.id}'
            )
            notifications.extend(agency_notifications)
        
        return notifications
    
    @staticmethod
    def notify_on_quota_warning(tenant, percentage_used: int):
        """Notify when tenant reaches quota threshold."""
        notifications = []
        
        # Notify tenant admins
        tenant_notifications = NotificationService.notify_tenant_admins(
            tenant=tenant,
            notification_type=NotificationType.QUOTA_WARNING,
            title='Quota Warning',
            message=f'You have used {percentage_used}% of your monthly message quota',
            priority=NotificationPriority.HIGH if percentage_used >= 90 else NotificationPriority.MEDIUM,
            metadata={
                'tenant_id': str(tenant.id),
                'percentage_used': percentage_used,
                'quota_limit': tenant.monthly_message_limit
            },
            action_url='/dashboard/settings'
        )
        notifications.extend(tenant_notifications)
        
        # Also notify agency admins if agency exists
        if tenant.agency:
            agency_notifications = NotificationService.notify_agency_admins(
                agency=tenant.agency,
                notification_type=NotificationType.QUOTA_WARNING,
                title='Client Quota Warning',
                message=f'{tenant.name} has used {percentage_used}% of their quota',
                priority=NotificationPriority.MEDIUM,
                metadata={
                    'tenant_id': str(tenant.id),
                    'tenant_name': tenant.name,
                    'percentage_used': percentage_used,
                    'agency_id': str(tenant.agency.id)
                }
            )
            notifications.extend(agency_notifications)
        
        return notifications
    
    @staticmethod
    def notify_on_plan_expiry(tenant, days_remaining: int):
        """Notify when tenant's plan is expiring soon."""
        return NotificationService.notify_tenant_admins(
            tenant=tenant,
            notification_type=NotificationType.PLAN_EXPIRING,
            title='Plan Expiring Soon',
            message=f'Your {tenant.get_plan_type_display()} plan expires in {days_remaining} days',
            priority=NotificationPriority.HIGH if days_remaining <= 7 else NotificationPriority.MEDIUM,
            metadata={
                'tenant_id': str(tenant.id),
                'days_remaining': days_remaining,
                'plan_type': tenant.plan_type,
                'expiry_date': str(tenant.plan_expiry_date)
            },
            action_url='/dashboard/settings'
        )
    
    @staticmethod
    def notify_on_new_client(tenant, created_by=None):
        """Notify agency admins when a new client is created under their agency."""
        notifications = []
        
        # Only notify agency admins if client belongs to an agency
        # Super admin does NOT need operational notifications about new clients
        if tenant.agency:
            agency_notifications = NotificationService.notify_agency_admins(
                agency=tenant.agency,
                notification_type=NotificationType.NEW_CLIENT,
                title='New Client Added',
                message=f'New client "{tenant.name}" has been added to your agency',
                priority=NotificationPriority.LOW,
                metadata={
                    'tenant_id': str(tenant.id),
                    'tenant_name': tenant.name,
                    'agency_id': str(tenant.agency.id),
                    'created_by': str(created_by.id) if created_by else None
                },
                action_url=f'/dashboard/clients/{tenant.id}'
            )
            notifications.extend(agency_notifications)
        
        return notifications
    
    @staticmethod
    def notify_on_new_agency(agency, created_by=None):
        """Notify super admins when a new agency is created."""
        return NotificationService.notify_super_admins(
            notification_type=NotificationType.NEW_AGENCY,
            title='New Agency Created',
            message=f'New agency "{agency.name}" has been created',
            priority=NotificationPriority.LOW,
            metadata={
                'agency_id': str(agency.id),
                'agency_name': agency.name,
                'created_by': str(created_by.id) if created_by else None
            },
            action_url=f'/dashboard/agencies/{agency.id}'
        )
    
    @staticmethod
    def notify_on_new_user_added(user, added_by=None):
        """Notify tenant admins when a new user is added to their tenant."""
        if not user.tenant:
            return []
        
        return NotificationService.notify_tenant_admins(
            tenant=user.tenant,
            notification_type=NotificationType.USER_REGISTERED,
            title='New Team Member',
            message=f'{user.email} ({user.get_role_display()}) has been added to your team',
            priority=NotificationPriority.LOW,
            metadata={
                'user_id': str(user.id),
                'user_email': user.email,
                'role': user.role,
                'added_by': str(added_by.id) if added_by else None
            },
            action_url='/dashboard/settings?tab=team'
        )
    
    # ============================================
    # System/Security notifications (Super Admin)
    # ============================================
    
    @staticmethod
    def notify_on_system_error(
        error_type: str,
        title: str,
        message: str,
        metadata: Optional[dict] = None
    ) -> List[Notification]:
        """
        Notify super admins of system errors.
        
        Use for:
        - Database errors
        - Critical service failures
        - Integration failures
        """
        return NotificationService.notify_super_admins(
            notification_type=NotificationType.SYSTEM_ERROR,
            title=title,
            message=message,
            priority=NotificationPriority.HIGH,
            metadata={
                'error_type': error_type,
                **(metadata or {})
            }
        )
    
    @staticmethod
    def notify_on_campaign_failed(campaign, error_message: str) -> List[Notification]:
        """Notify super admins, agency, and tenant when a campaign fails."""
        notifications = []
        
        # Notify super admins (system/operational oversight)
        super_notifications = NotificationService.notify_super_admins(
            notification_type=NotificationType.CAMPAIGN_FAILED,
            title='Campaign Failed',
            message=f'Campaign "{campaign.name}" for {campaign.tenant.name} failed: {error_message}',
            priority=NotificationPriority.HIGH,
            metadata={
                'campaign_id': str(campaign.id),
                'campaign_name': campaign.name,
                'tenant_id': str(campaign.tenant.id),
                'tenant_name': campaign.tenant.name,
                'error': error_message
            }
        )
        notifications.extend(super_notifications)
        
        # Notify the tenant
        tenant_notifications = NotificationService.notify_tenant_admins(
            tenant=campaign.tenant,
            notification_type=NotificationType.CAMPAIGN_FAILED,
            title='Campaign Failed',
            message=f'Your campaign "{campaign.name}" failed: {error_message}',
            priority=NotificationPriority.HIGH,
            metadata={
                'campaign_id': str(campaign.id),
                'error': error_message
            },
            action_url=f'/dashboard/campaigns/{campaign.id}'
        )
        notifications.extend(tenant_notifications)
        
        # Notify agency if tenant has one
        if campaign.tenant.agency:
            agency_notifications = NotificationService.notify_agency_admins(
                agency=campaign.tenant.agency,
                notification_type=NotificationType.CAMPAIGN_FAILED,
                title='Client Campaign Failed',
                message=f'{campaign.tenant.name}: Campaign "{campaign.name}" failed',
                priority=NotificationPriority.HIGH,
                metadata={
                    'campaign_id': str(campaign.id),
                    'tenant_id': str(campaign.tenant.id),
                    'error': error_message
                }
            )
            notifications.extend(agency_notifications)
        
        return notifications
    
    @staticmethod
    def _sanitize_error_message(error_message: str, max_length: int = 100) -> str:
        """
        Sanitize error message to avoid exposing sensitive details.
        Truncates and removes potentially sensitive information.
        """
        if not error_message:
            return "An error occurred"
        
        # Remove potential sensitive patterns (API keys, tokens, etc.)
        import re
        sanitized = re.sub(r'(token|key|secret|password|auth)[=:]\s*\S+', r'\1=[REDACTED]', error_message, flags=re.IGNORECASE)
        sanitized = re.sub(r'Bearer\s+\S+', 'Bearer [REDACTED]', sanitized)
        
        # Truncate to max length
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length] + '...'
        
        return sanitized
    
    @staticmethod
    def notify_on_api_error(
        tenant,
        error_type: str,
        error_message: str,
        metadata: Optional[dict] = None
    ) -> List[Notification]:
        """Notify when WhatsApp API or other integration fails."""
        notifications = []
        
        # Sanitize error message for user-facing notifications
        safe_error = NotificationService._sanitize_error_message(error_message)
        
        # Notify super admin (gets full error details in metadata only)
        super_notifications = NotificationService.notify_super_admins(
            notification_type=NotificationType.API_ERROR,
            title='API Error',
            message=f'{tenant.name}: {error_type} - {safe_error}',
            priority=NotificationPriority.HIGH,
            metadata={
                'tenant_id': str(tenant.id),
                'tenant_name': tenant.name,
                'error_type': error_type,
                'error_details': error_message,  # Full error for debugging (metadata only)
                **(metadata or {})
            }
        )
        notifications.extend(super_notifications)
        
        # Notify tenant (sanitized message only)
        tenant_notifications = NotificationService.notify_tenant_admins(
            tenant=tenant,
            notification_type=NotificationType.API_ERROR,
            title='API Error',
            message=f'{error_type}: {safe_error}',
            priority=NotificationPriority.HIGH,
            metadata={
                'error_type': error_type
            }
        )
        notifications.extend(tenant_notifications)
        
        # Notify agency if tenant has one (sanitized message only)
        if tenant.agency:
            agency_notifications = NotificationService.notify_agency_admins(
                agency=tenant.agency,
                notification_type=NotificationType.API_ERROR,
                title='Client API Error',
                message=f'{tenant.name}: {error_type} - {safe_error}',
                priority=NotificationPriority.HIGH,
                metadata={
                    'tenant_id': str(tenant.id),
                    'error_type': error_type
                }
            )
            notifications.extend(agency_notifications)
        
        return notifications

