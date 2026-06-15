"""
Custom User model for Multi-Tenant SaaS.
Supports SUPER_ADMIN, AGENCY_ADMIN, TENANT_ADMIN, and TENANT_USER roles.
"""
import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserRole(models.TextChoices):
    """User role choices."""
    SUPER_ADMIN = 'SUPER_ADMIN', 'Super Admin'
    AGENCY_ADMIN = 'AGENCY_ADMIN', 'Agency Admin'
    TENANT_ADMIN = 'TENANT_ADMIN', 'Tenant Admin'
    TENANT_USER = 'TENANT_USER', 'Tenant User'


class UserManager(BaseUserManager):
    """Custom user manager."""
    
    def create_user(self, email, password=None, **extra_fields):
        """Create and return a regular user."""
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        """Create and return a super admin user."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', UserRole.SUPER_ADMIN)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model with role-based access.
    
    Roles:
    - SUPER_ADMIN: Platform owner, can manage all tenants & agencies
    - AGENCY_ADMIN: Agency owner, can manage clients under their agency
    - TENANT_ADMIN: Client owner, can manage own tenant
    - TENANT_USER: Limited access within tenant
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    
    # Role
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.TENANT_USER
    )
    
    # Agency (for Agency Admins)
    agency = models.ForeignKey(
        'tenants.Agency',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        help_text='For Agency Admins'
    )
    
    # Tenant (for Tenant Admins/Users)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='users',
        help_text='Null for Super Admins and Agency Admins'
    )
    
    # Status
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    
    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-created_at']
    
    def __str__(self):
        return self.email
    
    @property
    def full_name(self):
        """Return full name."""
        return f"{self.first_name} {self.last_name}".strip() or self.email
    
    @property
    def is_super_admin(self):
        return self.role == UserRole.SUPER_ADMIN
    
    @property
    def is_agency_admin(self):
        return self.role == UserRole.AGENCY_ADMIN
    
    @property
    def is_tenant_admin(self):
        return self.role == UserRole.TENANT_ADMIN
