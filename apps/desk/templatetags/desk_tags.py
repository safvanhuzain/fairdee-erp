from django import template
from django.utils import formats

register = template.Library()


@register.filter
def desk_cell(obj, key):
    """Render a list cell for mixed FK / scalar fields."""
    if key == 'company':
        c = getattr(obj, 'company', None)
        return c.name if c else '—'
    val = getattr(obj, key, None)
    if val is None:
        return '—'
    if hasattr(val, 'strftime'):
        if key in ('created_at', 'updated_at'):
            return formats.date_format(val, 'SHORT_DATETIME_FORMAT')
        return formats.date_format(val, 'SHORT_DATE_FORMAT')
    if isinstance(val, bool):
        return 'Yes' if val else 'No'
    return val
