from django.contrib import admin

from .models import RoleProfile


@admin.register(RoleProfile)
class RoleProfileAdmin(admin.ModelAdmin):
    list_display = ('slug', 'group', 'company', 'updated_at')
    list_filter = ('company',)
    search_fields = ('slug', 'description', 'group__name')
    autocomplete_fields = ('group', 'company')
