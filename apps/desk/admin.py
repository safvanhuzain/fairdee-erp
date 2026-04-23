from django.contrib import admin

from apps.desk.models import DataImport


@admin.register(DataImport)
class DataImportAdmin(admin.ModelAdmin):
    list_display = ('id', 'content_type', 'mode', 'status', 'rows_created', 'rows_updated', 'rows_failed', 'created_at')
    list_filter = ('status', 'mode')
    readonly_fields = ('error_report', 'rows_created', 'rows_updated', 'rows_failed', 'created_at')
