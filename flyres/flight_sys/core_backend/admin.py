from django.contrib import admin
from .models import FlightOffer, Reservation, AuditLog, CustomUser
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model

User = get_user_model()
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(CustomUser)  # Register the CustomUser model
class CustomUserAdmin(BaseUserAdmin):  # Inherit from UserAdmin for better default functionality
    list_display = ('username', 'email',  'is_verified')
    list_filter = ('is_staff', 'is_superuser', 'is_verified')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    ordering = ('username',)
    
    fieldsets = (
        (None, {
            'fields': ('username', 'password')
        }),
        # ('Personal Info', {
        #     'fields': ('first_name', 'last_name', 'email')
        # }),
        ('User Info', {
            'fields': ('first_name', 'last_name', 'email', 'phone_number')
        }),
        ('Permissions', {
            'fields': ('is_verified', 'is_active', 'is_staff', 'is_superuser', 
                      'groups', 'user_permissions')
        }),
        ('Important dates', {
            'fields': ('last_login', 'date_joined')
        }),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2'),
        }),
    )

# Register your models here.
admin.site.register(FlightOffer)
admin.site.register(Reservation)
admin.site.register(AuditLog)