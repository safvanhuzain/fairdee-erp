# Generated manually: rename name -> currency_name + ERPNext-style Currency fields.

from decimal import Decimal

import django.core.validators
from django.db import migrations, models

_CURRENCY_NUMBER_FORMAT_CHOICES = [('', '—')] + [
    ('#,###.##', '#,###.##'),
    ('#.###,##', '#.###,##'),
    ('# ###.##', '# ###.##'),
    ('# ###,##', '# ###,##'),
    ("#'###.##", "#'###.##"),
    ('#, ###.##', '#, ###.##'),
    ('#,##,###.##', '#,##,###.##'),
    ('#,###.###', '#,###.###'),
    ('#.###', '#.###'),
    ('#,###', '#,###'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_country'),
    ]

    operations = [
        migrations.RenameField(
            model_name='currency',
            old_name='name',
            new_name='currency_name',
        ),
        migrations.AlterField(
            model_name='currency',
            name='currency_name',
            field=models.CharField(db_index=True, max_length=255, unique=True),
        ),
        migrations.AddField(
            model_name='currency',
            name='enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='currency',
            name='fraction',
            field=models.CharField(
                blank=True,
                help_text='Sub-currency label, e.g. "Cent".',
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name='currency',
            name='fraction_units',
            field=models.IntegerField(
                blank=True,
                help_text='How many fraction units per 1 main unit (e.g. 100 for USD cents).',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='currency',
            name='smallest_currency_fraction_value',
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text='Smallest circulating fraction (e.g. 0.01 for 1 cent).',
                max_digits=18,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
            ),
        ),
        migrations.AddField(
            model_name='currency',
            name='symbol',
            field=models.CharField(
                blank=True,
                help_text='Display symbol, e.g. $.',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='currency',
            name='number_format',
            field=models.CharField(
                blank=True,
                choices=_CURRENCY_NUMBER_FORMAT_CHOICES,
                help_text='How amounts are formatted; leave blank for system defaults.',
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name='currency',
            name='symbol_on_right',
            field=models.BooleanField(
                default=False,
                help_text='Show currency symbol on the right side of amounts.',
            ),
        ),
    ]
