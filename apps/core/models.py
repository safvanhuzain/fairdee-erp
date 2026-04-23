from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

# ERPNext Currency.number_format options (see Currency DocType).
_CURRENCY_NUMBER_FORMAT_LINES = """
#,###.##
#.###,##
# ###.##
# ###,##
#'###.##
#, ###.##
#,##,###.##
#,###.###
#.###
#,###
""".strip().splitlines()


class Currency(models.Model):
    """
    Currency master aligned with ERPNext Currency DocType fields;
    used by finance.Account (ISO code + display metadata).
    """

    allow_bulk_upload = True

    CURRENCY_NUMBER_FORMAT_CHOICES = [('', '—')] + [
        (line.strip(), line.strip()) for line in _CURRENCY_NUMBER_FORMAT_LINES if line.strip()
    ]

    code = models.CharField(max_length=3, unique=True, db_index=True)
    currency_name = models.CharField(max_length=255, unique=True, db_index=True)
    enabled = models.BooleanField(default=False)
    fraction = models.CharField(
        max_length=64,
        blank=True,
        help_text='Sub-currency label, e.g. "Cent".',
    )
    fraction_units = models.IntegerField(
        null=True,
        blank=True,
        help_text='How many fraction units per 1 main unit (e.g. 100 for USD cents).',
    )
    smallest_currency_fraction_value = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Smallest circulating fraction (e.g. 0.01 for 1 cent).',
    )
    symbol = models.CharField(
        max_length=16,
        blank=True,
        help_text='Display symbol, e.g. $.',
    )
    number_format = models.CharField(
        max_length=32,
        choices=CURRENCY_NUMBER_FORMAT_CHOICES,
        blank=True,
        help_text='How amounts are formatted; leave blank for system defaults.',
    )
    symbol_on_right = models.BooleanField(
        default=False,
        help_text='Show currency symbol on the right side of amounts.',
    )

    class Meta:
        ordering = ['code']
        verbose_name_plural = 'currencies'

    def __str__(self) -> str:
        return f'{self.code} — {self.currency_name}'


class Country(models.Model):
    """
    Country master aligned with ERPNext Country-style fields
    (country name, date/time format, time zones text, ISO alpha-2 code).
    """

    allow_bulk_upload = True

    country_name = models.CharField(max_length=255, unique=True, db_index=True)
    date_format = models.CharField(
        max_length=64,
        blank=True,
        help_text='Python/strftime-style or locale date pattern used for this country.',
    )
    time_format = models.CharField(
        max_length=32,
        default='HH:mm:ss',
        blank=True,
    )
    time_zones = models.TextField(
        blank=True,
        help_text='Typical time zones for this country (e.g. one IANA id per line).',
    )
    code = models.CharField(
        max_length=2,
        unique=True,
        db_index=True,
        help_text="The country's ISO 3166-1 alpha-2 code (two letters).",
    )

    class Meta:
        ordering = ['country_name']
        verbose_name_plural = 'countries'

    def __str__(self) -> str:
        return f'{self.country_name} ({self.code})'


class Company(models.Model):
    """Tenant / legal entity for finance data isolation."""

    allow_bulk_upload = True

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=64, unique=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'companies'

    def __str__(self) -> str:
        return self.name
