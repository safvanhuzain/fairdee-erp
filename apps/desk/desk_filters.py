"""
Server-side list filters for desk auto-document lists (Frappe-inspired row UI).

Filter rows are submitted as GET parameters::

    d0_field=name&d0_op=contains&d0_val=foo&d1_field=...

Rows are ANDed. Field names and operators are validated against the model;
invalid rows are skipped (with optional error messages for UX).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import models
from django.db.models import BinaryField, Q

# --- Field discovery ---------------------------------------------------------

_SKIP_FIELD_NAMES = frozenset({'password'})


def filterable_fields_for_model(model) -> list[dict[str, Any]]:
    """Metadata for filter dropdowns + operator sets (built in JS from ``ops``)."""
    out: list[dict[str, Any]] = []
    for f in model._meta.fields:
        if f.name in _SKIP_FIELD_NAMES:
            continue
        if isinstance(f, BinaryField):
            continue
        if getattr(f, 'auto_created', False) and not f.concrete:
            continue
        kind, ops = _field_kind_and_ops(f)
        if not ops:
            continue
        out.append(
            {
                'name': f.name,
                'label': str(f.verbose_name).title() if f.verbose_name else f.name.replace('_', ' ').title(),
                'kind': kind,
                'ops': [{'value': o, 'label': OPERATOR_LABELS.get(o, o.replace('_', ' ').title())} for o in ops],
            }
        )
    return out


def _field_kind_and_ops(field) -> tuple[str, list[str]]:
    if isinstance(
        field,
        (
            models.CharField,
            models.TextField,
            models.EmailField,
            models.SlugField,
            models.URLField,
            models.GenericIPAddressField,
            models.UUIDField,
        ),
    ):
        return 'string', ['equals', 'not_equals', 'like', 'not_like', 'is', 'is_not']
    if isinstance(field, (models.BooleanField, models.NullBooleanField)):
        ops = ['equals', 'not_equals']
        if field.null:
            ops.extend(['is', 'is_not'])
        return 'bool', ops
    if isinstance(
        field,
        (
            models.IntegerField,
            models.BigIntegerField,
            models.SmallIntegerField,
            models.PositiveIntegerField,
            models.PositiveSmallIntegerField,
        ),
    ):
        ops = ['equals', 'not_equals', 'gt', 'gte', 'lt', 'lte']
        if field.null:
            ops.extend(['is', 'is_not'])
        return 'number', ops
    if isinstance(field, (models.DecimalField, models.FloatField)):
        ops = ['equals', 'not_equals', 'gt', 'gte', 'lt', 'lte']
        if field.null:
            ops.extend(['is', 'is_not'])
        return 'number', ops
    if isinstance(field, (models.DateField, models.DateTimeField)):
        ops = ['equals', 'not_equals', 'gt', 'gte', 'lt', 'lte']
        if field.null:
            ops.extend(['is', 'is_not'])
        return 'date', ops
    if isinstance(field, (models.ForeignKey, models.OneToOneField)):
        ops = ['equals', 'not_equals']
        if field.null:
            ops.extend(['is', 'is_not'])
        return 'fk', ops
    if isinstance(field, models.JSONField):
        return 'other', []
    if field.primary_key and field.get_internal_type() in ('AutoField', 'BigAutoField', 'SmallAutoField'):
        return 'number', ['equals', 'not_equals', 'gt', 'gte', 'lt', 'lte']
    return 'other', ['equals', 'not_equals'] if not field.null else ['equals', 'not_equals', 'is', 'is_not']


# Human labels for operators (Frappe-ish naming)
OPERATOR_LABELS = {
    'equals': 'Equals',
    'not_equals': 'Not equals',
    'like': 'Like',
    'not_like': 'Not like',
    'gt': 'Greater than',
    'gte': 'Greater or equal',
    'lt': 'Less than',
    'lte': 'Less or equal',
    'is': 'Is set',
    'is_not': 'Is not set',
}


# --- Parsing GET -> Q --------------------------------------------------------


def iter_desk_filter_rows(get) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for i in range(32):
        fk = f'd{i}_field'
        if fk not in get:
            break
        field = (get.get(fk) or '').strip()
        op = (get.get(f'd{i}_op') or 'equals').strip()
        val = get.get(f'd{i}_val', '')
        if hasattr(val, 'strip'):
            val = val.strip()
        else:
            val = str(val)
        rows.append((field, op, val))
    return rows


def _parse_bool(raw: str) -> bool | None:
    s = raw.strip().lower()
    if s in ('1', 'true', 'yes', 'on'):
        return True
    if s in ('0', 'false', 'no', 'off', ''):
        return False
    return None


def _coerce_scalar(field, raw: str) -> Any:
    raw = (raw or '').strip()
    if isinstance(field, models.BooleanField):
        b = _parse_bool(raw)
        if b is None:
            raise ValueError('Use true/false, yes/no, or 1/0.')
        return b
    if isinstance(field, (models.IntegerField, models.BigIntegerField, models.SmallIntegerField)):
        return int(raw)
    if isinstance(field, models.PositiveIntegerField):
        v = int(raw)
        if v < 0:
            raise ValueError('Must be a positive integer.')
        return v
    if isinstance(field, models.PositiveSmallIntegerField):
        v = int(raw)
        if v < 0:
            raise ValueError('Must be a positive integer.')
        return v
    if isinstance(field, (models.DecimalField, models.FloatField)):
        try:
            return Decimal(raw) if isinstance(field, models.DecimalField) else float(raw)
        except (InvalidOperation, ValueError) as e:
            raise ValueError('Invalid number.') from e
    if isinstance(field, models.DateTimeField):
        from django.utils.dateparse import parse_datetime

        dt = parse_datetime(raw)
        if dt is None:
            raise ValueError('Invalid datetime (use ISO format, e.g. 2024-01-15 10:30:00).')
        return dt
    if isinstance(field, models.DateField):
        from django.utils.dateparse import parse_date

        d = parse_date(raw)
        if d is None:
            raise ValueError('Invalid date (use YYYY-MM-DD).')
        return d
    if isinstance(field, (models.ForeignKey, models.OneToOneField)):
        rel = field.remote_field.model
        meta = rel._meta
        pk = meta.pk
        if isinstance(pk, models.AutoField) or isinstance(pk, models.BigAutoField) or isinstance(
            pk, models.IntegerField
        ):
            return int(raw)
        if isinstance(pk, models.UUIDField):
            import uuid

            return uuid.UUID(raw)
        return raw
    return raw


def _q_for_row(model, field_name: str, op: str, val: str) -> tuple[Q | None, str | None]:
    """
    Build one Q for a validated row. Returns (Q, error_message).
    error_message set => skip row (or caller may flash).
    """
    try:
        field = model._meta.get_field(field_name)
    except Exception:
        return None, f'Unknown field: {field_name}'

    _kind, allowed = _field_kind_and_ops(field)
    if op not in allowed:
        return None, f'Operator not allowed for this field: {op}'

    attname = field.attname

    # is / is_not => "is set" / "is not set" (Frappe-style)
    if op == 'is':
        if isinstance(field, (models.CharField, models.TextField)):
            if field.null:
                return Q(**{f'{field.name}__isnull': False}) & ~Q(**{f'{field.name}': ''}), None
            return ~Q(**{f'{field.name}': ''}), None
        if isinstance(field, (models.ForeignKey, models.OneToOneField)):
            if field.null:
                return Q(**{f'{attname}__isnull': False}), None
            return None, 'This relation is always set.'
        if field.null:
            return Q(**{f'{attname}__isnull': False}), None
        return None, '"Is set" does not apply to this field.'
    if op == 'is_not':
        if isinstance(field, (models.CharField, models.TextField)):
            if field.null:
                return Q(**{f'{field.name}__isnull': True}) | Q(**{f'{field.name}': ''}), None
            return Q(**{f'{field.name}': ''}), None
        if isinstance(field, (models.ForeignKey, models.OneToOneField)):
            if field.null:
                return Q(**{f'{attname}__isnull': True}), None
            return None, 'This relation is always set.'
        if field.null:
            return Q(**{f'{attname}__isnull': True}), None
        return None, '"Is not set" does not apply to this field.'

    if not val and op not in ('is', 'is_not'):
        return None, None  # skip empty value rows silently

    try:
        coerced = _coerce_scalar(field, val)
    except ValueError as e:
        return None, str(e)
    except Exception:
        return None, 'Invalid value.'

    lookup = attname

    if isinstance(
        field,
        (
            models.CharField,
            models.TextField,
            models.EmailField,
            models.SlugField,
            models.URLField,
            models.GenericIPAddressField,
        ),
    ):
        if op == 'equals':
            return Q(**{f'{field.name}__iexact': coerced}), None
        if op == 'not_equals':
            return ~Q(**{f'{field.name}__iexact': coerced}), None
        if op == 'like':
            return Q(**{f'{field.name}__icontains': coerced}), None
        if op == 'not_like':
            return ~Q(**{f'{field.name}__icontains': coerced}), None

    if isinstance(field, models.UUIDField):
        if op == 'equals':
            return Q(**{lookup: coerced}), None
        if op == 'not_equals':
            return ~Q(**{lookup: coerced}), None

    if isinstance(field, models.BooleanField):
        if op == 'equals':
            return Q(**{lookup: coerced}), None
        if op == 'not_equals':
            return ~Q(**{lookup: coerced}), None

    if isinstance(field, (models.ForeignKey, models.OneToOneField)):
        if op == 'equals':
            return Q(**{lookup: coerced}), None
        if op == 'not_equals':
            return ~Q(**{lookup: coerced}), None

    # numbers, dates
    if op == 'equals':
        return Q(**{lookup: coerced}), None
    if op == 'not_equals':
        return ~Q(**{lookup: coerced}), None
    if op == 'gt':
        return Q(**{f'{lookup}__gt': coerced}), None
    if op == 'gte':
        return Q(**{f'{lookup}__gte': coerced}), None
    if op == 'lt':
        return Q(**{f'{lookup}__lt': coerced}), None
    if op == 'lte':
        return Q(**{f'{lookup}__lte': coerced}), None

    return None, f'Unsupported combination: {field_name} {op}'


def build_filter_q(model, get) -> tuple[Q | None, list[str], list[dict[str, str]]]:
    """
    Returns (combined_and_q_or_none, errors, rows_echo for template).

    ``rows_echo`` is each row as dict field/op/value for repopulating the form.
    """
    errors: list[str] = []
    row_qs: list[Q] = []
    echo: list[dict[str, str]] = []
    for field_name, op, val in iter_desk_filter_rows(get):
        echo.append({'field': field_name, 'op': op, 'val': val})
        if not field_name:
            continue
        q, err = _q_for_row(model, field_name, op, val)
        if err:
            errors.append(err)
            continue
        if q is None:
            continue
        row_qs.append(q)
    if not row_qs:
        return None, errors, echo
    combined = row_qs[0]
    for q in row_qs[1:]:
        combined = combined & q
    return combined, errors, echo


def preserved_list_querystring(get) -> str:
    """GET query without ``page`` (for pagination links)."""
    q = get.copy()
    q.pop('page', None)
    return q.urlencode()


def list_querystring_with_page_size(get, new_size: int, *, default_size: int = 20) -> str:
    """
    GET query for list view when switching page length: drop ``page``, set ``page_size``.

    Omits ``page_size`` when *new_size* equals *default_size* (shorter URLs, same as Frappe-style default).
    """
    q = get.copy()
    q.pop('page', None)
    if int(new_size) == int(default_size):
        q.pop('page_size', None)
    else:
        q['page_size'] = str(int(new_size))
    return q.urlencode()
