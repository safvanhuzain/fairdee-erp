from django.contrib import admin

from .models import Account, CostCenter, Invoice, JournalEntry, JournalLine, PurchaseInvoice


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = (
        'account_name',
        'account_number',
        'company',
        'is_group',
        'root_type',
        'report_type',
        'parent_account',
        'disabled',
    )
    list_filter = ('company', 'is_group', 'root_type', 'report_type', 'disabled')
    search_fields = ('account_name', 'account_number')
    autocomplete_fields = (
        'company',
        'parent_account',
        'account_currency',
    )


@admin.register(CostCenter)
class CostCenterAdmin(admin.ModelAdmin):
    list_display = (
        'cost_center_name',
        'cost_center_number',
        'company',
        'is_group',
        'parent_cost_center',
        'disabled',
        'lft',
        'rgt',
    )
    list_filter = ('company', 'is_group', 'disabled')
    search_fields = ('cost_center_name', 'cost_center_number')
    autocomplete_fields = ('company', 'parent_cost_center')


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0


@admin.register(PurchaseInvoice)
class PurchaseInvoiceAdmin(admin.ModelAdmin):
    list_display = ('number', 'company', 'currency', 'total_amount', 'status', 'created_at')
    list_filter = ('status', 'company')
    search_fields = ('number',)
    autocomplete_fields = ('company', 'created_by')


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('number', 'company', 'currency', 'total_amount', 'status', 'created_at')
    list_filter = ('status', 'company')
    search_fields = ('number',)
    autocomplete_fields = ('company', 'created_by')


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'posting_date', 'reference', 'created_at')
    list_filter = ('company',)
    search_fields = ('reference', 'memo')
    autocomplete_fields = ('company', 'created_by')
    inlines = [JournalLineInline]


@admin.register(JournalLine)
class JournalLineAdmin(admin.ModelAdmin):
    list_display = ('id', 'entry', 'account_code', 'debit', 'credit')
    list_filter = ('entry__company',)
    search_fields = ('account_code', 'description')
