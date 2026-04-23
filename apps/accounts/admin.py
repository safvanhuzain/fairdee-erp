from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ('email',)
    list_display = (
        'email',
        'first_name',
        'last_name',
        'company',
        'is_staff',
        'is_active',
    )
    list_filter = ('is_staff', 'is_active', 'company')
    search_fields = ('email', 'first_name', 'last_name')
    autocomplete_fields = ('company',)
    filter_horizontal = ('groups', 'user_permissions')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Profile', {'fields': ('first_name', 'last_name', 'company', 'metadata')}),
        (
            'Permissions',
            {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')},
        ),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': (
                    'email',
                    'password1',
                    'password2',
                    'first_name',
                    'last_name',
                    'company',
                    'is_staff',
                    'is_superuser',
                    'groups',
                    'user_permissions',
                ),
            },
        ),
    )
