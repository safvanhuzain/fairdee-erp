"""
CSV import execution for :class:`~apps.desk.models.DataImport`.

Headers should match model field names (case-insensitive). Use ``id`` for the
primary key when upserting. Export a Google Sheet as CSV to upload here.
"""

from __future__ import annotations

import csv
import io
from contextlib import suppress
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import Q
from django.utils.dateparse import parse_date, parse_datetime


def _normalize_header(name: str) -> str:
    if name is None:
        return ''
    return name.strip().lstrip('\ufeff').lower().replace(' ', '_')


def _writable_fields(target_model):
    """Concrete non-relation fields suitable for CSV (excluding reverse relations)."""
    skip_types = (models.ManyToManyField,)
    for f in target_model._meta.local_concrete_fields:
        if isinstance(f, skip_types):
            continue
        if isinstance(f, models.BinaryField):
            continue
        if not getattr(f, 'editable', True) and not f.primary_key:
            continue
        yield f


def _header_to_field_map(target_model) -> dict[str, models.Field]:
    m: dict[str, models.Field] = {}
    for f in _writable_fields(target_model):
        m[f.name.lower()] = f
        m[f.attname.lower()] = f
    pk = target_model._meta.pk
    if pk.name.lower() not in m:
        m['id'] = pk
    return m


def _strip_wrapping_quotes(s: str) -> str:
    """Remove one layer of straight or curly quotes often added by Excel/Sheets."""
    s = (s or '').strip()
    if len(s) < 2:
        return s
    pairs = (
        ('"', '"'),
        ("'", "'"),
        ('\u201c', '\u201d'),
        ('\u2018', '\u2019'),
    )
    for open_q, close_q in pairs:
        if s.startswith(open_q) and s.endswith(close_q):
            return s[len(open_q) : -len(close_q)].strip()
    return s


def _resolve_fk_pk(field: models.ForeignKey | models.OneToOneField, raw: str, context: dict[str, Any]) -> int | None:
    """
    Return the related primary key for a CSV cell.

    Numeric values are treated as PKs. Otherwise we resolve common masters by
    natural key (e.g. company name/slug, currency ISO code).
    """
    raw = _strip_wrapping_quotes(raw)
    if not raw:
        return None
    rel = field.remote_field.model
    meta = rel._meta
    label = meta.label_lower

    try:
        return int(raw)
    except ValueError:
        pass

    if label == 'core.company':
        obj = rel.objects.filter(Q(name__iexact=raw) | Q(slug__iexact=raw)).first()
        if obj is None:
            raise ValueError(f'no company matches {raw!r} (use name, slug, or numeric id)')
        return int(obj.pk)

    if label == 'core.currency':
        code = raw.strip().upper()
        obj = (
            rel.objects.filter(code__iexact=code).first()
            or rel.objects.filter(currency_name__iexact=raw).first()
        )
        if obj is None:
            raise ValueError(f'no currency matches {raw!r} (use code, e.g. THB, currency name, or id)')
        return int(obj.pk)

    if label == 'core.country':
        obj = rel.objects.filter(code__iexact=raw.upper()).first() or rel.objects.filter(
            country_name__iexact=raw
        ).first()
        if obj is None:
            raise ValueError(f'no country matches {raw!r} (use ISO code, country name, or id)')
        return int(obj.pk)

    if label == 'auth.group':
        obj = rel.objects.filter(name__iexact=raw).first()
        if obj is None:
            raise ValueError(f'no group matches {raw!r} (use group name or id)')
        return int(obj.pk)

    # Self-FK on chart of accounts: match parent by name/number within company when known.
    if rel == field.model and meta.label_lower == 'finance.account':
        cid = context.get('company_id')
        qs = rel.objects.all()
        if cid is not None:
            qs = qs.filter(company_id=cid)
        obj = qs.filter(account_name__iexact=raw).first()
        if obj is None:
            obj = qs.filter(account_number=raw).first()
        if obj is None:
            scope = 'this company' if cid is not None else 'any'
            raise ValueError(f'no account matches {raw!r} ({scope}; put company before parent_account in CSV if needed)')
        return int(obj.pk)

    if rel == field.model and meta.label_lower == 'finance.costcenter':
        cid = context.get('company_id')
        qs = rel.objects.all()
        if cid is not None:
            qs = qs.filter(company_id=cid)
        obj = qs.filter(cost_center_name__iexact=raw).first()
        if obj is None:
            obj = qs.filter(cost_center_number=raw).first()
        if obj is None:
            scope = 'this company' if cid is not None else 'any'
            raise ValueError(
                f'no cost center matches {raw!r} ({scope}; put company before parent_cost_center in CSV if needed)'
            )
        return int(obj.pk)

    raise ValueError(f'for {field.name}, use the related numeric id (natural key lookup not defined for {label})')


def _coerce_value(field: models.Field, raw: str) -> Any:
    raw = _strip_wrapping_quotes(raw)
    if raw == '':
        return None
    if isinstance(field, (models.BooleanField, models.NullBooleanField)):
        s = raw.lower()
        if s in ('1', 'true', 'yes', 'y', 'on'):
            return True
        if s in ('0', 'false', 'no', 'n', 'off'):
            return False
        raise ValueError('expected true/false')
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
        return int(raw)
    if isinstance(field, (models.DecimalField, models.FloatField)):
        try:
            return Decimal(raw) if isinstance(field, models.DecimalField) else float(raw)
        except (InvalidOperation, ValueError) as e:
            raise ValueError('invalid number') from e
    if isinstance(field, models.DateTimeField):
        dt = parse_datetime(raw)
        if dt is None:
            raise ValueError('invalid datetime')
        return dt
    if isinstance(field, models.DateField):
        d = parse_date(raw)
        if d is None:
            raise ValueError('invalid date')
        return d
    if isinstance(field, models.UUIDField):
        import uuid

        return uuid.UUID(raw)
    return raw


def _row_to_kwargs(
    target_model,
    row: dict[str, str],
    field_by_norm: dict[str, models.Field],
    *,
    force_company_id: int | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for csv_col, cell in row.items():
        field = field_by_norm.get(_normalize_header(csv_col))
        if field is None:
            continue
        if cell is None or (isinstance(cell, str) and _strip_wrapping_quotes(cell) == ''):
            continue
        try:
            if isinstance(field, (models.ForeignKey, models.OneToOneField)):
                val = _resolve_fk_pk(field, str(cell), kwargs)
            else:
                val = _coerce_value(field, str(cell))
        except (ValueError, TypeError) as e:
            raise ValueError(f'{field.name}: {e}') from e
        if isinstance(field, (models.ForeignKey, models.OneToOneField)):
            kwargs[field.attname] = val
        else:
            kwargs[field.name] = val
    if force_company_id is not None:
        with suppress(Exception):
            target_model._meta.get_field('company')
            kwargs['company_id'] = force_company_id
    return kwargs


def run_data_import(data_import, acting_user) -> None:
    """
    Read ``data_import.attachment``, import rows into ``content_type`` model,
    and update counters + ``error_report`` on ``data_import``.
    """
    from apps.desk.models import DataImport

    target = data_import.content_type.model_class()
    if target is None:
        data_import.status = DataImport.Status.FAILED
        data_import.error_report = [{'row': 0, 'column': '', 'message': 'Invalid target model.'}]
        data_import.save(
            update_fields=['status', 'error_report', 'rows_created', 'rows_updated', 'rows_failed']
        )
        return

    if data_import.mode == DataImport.Mode.UPSERT:
        ch = f'{target._meta.app_label}.change_{target._meta.model_name}'
        if not acting_user.has_perm(ch):
            data_import.status = DataImport.Status.FAILED
            data_import.error_report = [
                {
                    'row': 0,
                    'column': '',
                    'message': 'Update-or-insert requires change permission on the target model.',
                }
            ]
            data_import.save(update_fields=['status', 'error_report'])
            return

    data_import.status = DataImport.Status.RUNNING
    data_import.save(update_fields=['status'])

    errors: list[dict[str, Any]] = []
    created = updated = failed = 0
    mode = data_import.mode
    force_company_id = getattr(acting_user, 'company_id', None) if not acting_user.is_superuser else None

    field_by_norm = _header_to_field_map(target)
    pk_field = target._meta.pk

    try:
        raw = data_import.attachment.read()
        if isinstance(raw, bytes):
            text = raw.decode('utf-8-sig')
        else:
            text = raw
    except Exception as e:
        data_import.status = DataImport.Status.FAILED
        data_import.error_report = [{'row': 0, 'column': '', 'message': f'Could not read file: {e}'}]
        data_import.save(update_fields=['status', 'error_report'])
        return

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        data_import.status = DataImport.Status.FAILED
        data_import.error_report = [{'row': 0, 'column': '', 'message': 'CSV has no header row.'}]
        data_import.save(update_fields=['status', 'error_report'])
        return

    row_num = 1
    for row in reader:
        row_num += 1
        if not any((v or '').strip() for v in row.values() if v is not None):
            continue
        try:
            kwargs = _row_to_kwargs(target, row, field_by_norm, force_company_id=force_company_id)
        except ValueError as e:
            failed += 1
            errors.append({'row': row_num, 'column': '', 'message': str(e)})
            continue

        pk_att = pk_field.attname
        pk_val = kwargs.pop(pk_att, None)
        if pk_val is None and pk_field.name in kwargs:
            pk_val = kwargs.pop(pk_field.name, None)

        try:
            with transaction.atomic():
                if mode == DataImport.Mode.UPSERT and pk_val is not None and str(pk_val).strip() != '':
                    try:
                        pk_coerced = _coerce_value(pk_field, str(pk_val))
                    except (ValueError, TypeError):
                        failed += 1
                        errors.append({'row': row_num, 'column': pk_field.name, 'message': 'Invalid primary key.'})
                        continue
                    try:
                        obj = target.objects.get(pk=pk_coerced)
                    except target.DoesNotExist:
                        obj = None
                    if obj is not None:
                        for k, v in kwargs.items():
                            setattr(obj, k, v)
                        obj.full_clean()
                        obj.save()
                        updated += 1
                        continue
                create_kwargs = dict(kwargs)
                if pk_val is not None and str(pk_val).strip() != '':
                    with suppress(ValueError, TypeError):
                        create_kwargs[pk_att] = _coerce_value(pk_field, str(pk_val))
                obj = target(**create_kwargs)
                obj.full_clean()
                obj.save()
                created += 1
        except (ValidationError, IntegrityError, TypeError, ValueError) as e:
            failed += 1
            msg = str(e)
            if isinstance(e, ValidationError) and getattr(e, 'error_dict', None):
                parts = []
                for k, v in e.error_dict.items():
                    parts.append(f'{k}: {", ".join(str(x) for x in v)}')
                msg = '; '.join(parts)
            errors.append({'row': row_num, 'column': '', 'message': msg[:500]})

    data_import.rows_created = created
    data_import.rows_updated = updated
    data_import.rows_failed = failed
    data_import.error_report = errors
    data_import.status = DataImport.Status.DONE
    data_import.save(
        update_fields=[
            'status',
            'rows_created',
            'rows_updated',
            'rows_failed',
            'error_report',
        ]
    )


def template_field_rows_for_model(target_model) -> list[dict[str, str]]:
    """Field metadata for the template picker (canonical CSV header = ``name``)."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for f in _writable_fields(target_model):
        if f.name in seen:
            continue
        seen.add(f.name)
        label = str(f.verbose_name) if f.verbose_name else f.name
        rows.append({'name': f.name, 'label': label.replace('"', "'")})
    rows.sort(key=lambda r: r['name'].lower())
    return rows


def validate_template_field_names(target_model, names: list[str]) -> tuple[list[str] | None, str | None]:
    """Return ordered unique field names allowed in a CSV template, or (None, error)."""
    allowed = {f.name for f in _writable_fields(target_model)}
    out: list[str] = []
    seen: set[str] = set()
    for raw in names:
        n = (raw or '').strip()
        if not n:
            continue
        if n not in allowed:
            return None, f'Unknown or disallowed field: {n}'
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    if not out:
        return None, 'Select at least one field.'
    return out, None


def build_template_csv_bytes(field_names: list[str]) -> bytes:
    """UTF-8 with BOM + single header row (no data rows)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\n')
    writer.writerow(field_names)
    return ('\ufeff' + buf.getvalue()).encode('utf-8')
