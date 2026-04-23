from django.contrib import admin

from .models import Company, Country, Currency


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ('country_name', 'code', 'date_format', 'time_format')
    search_fields = ('country_name', 'code', 'time_zones')


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'currency_name',
        'enabled',
        'symbol',
        'fraction',
        'fraction_units',
        'number_format',
    )
    list_filter = ('enabled', 'symbol_on_right')
    search_fields = ('code', 'currency_name', 'symbol', 'fraction')


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
