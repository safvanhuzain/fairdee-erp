"""
Reusable desk list + bulk delete for any model.

Subclass ``DeskDocumentListView``, set ``model``, ``page_title``, ``page_subtitle``,
``columns`` (list of ``{'key', 'label'}``), ``admin_url``, and ``get_queryset()`` if
you need custom ordering/scoping.

For **Core**, **Accounts** (except ``accounts.User``), **auth.Group**, and **finance** masters (e.g. ``Account``, ``CostCenter``), use
``DeskAutoDocumentListView`` via URL ``<app_label>/<model_name>/`` — no subclass
per model; see ``apps.desk.registry`` for discovery rules.

Requires Django model permissions ``<app>.view_<model>`` (list) and
``<app>.delete_<model>`` (bulk delete). Grant them via groups or user permissions.

Auto lists support **GET filters** (field + operator + value), combined with **AND**;
see ``apps.desk.desk_filters``.

**Page length** is controlled by validated GET ``page_size`` (``20``, ``100``, ``500``, ``2500``);
default ``20``. Same query string is preserved when changing page size (``page`` reset).

**Sort** (auto lists only): GET ``sort`` (field name) and ``sort_dir`` (``asc`` / ``desc``), validated
against the same field set as filters plus the primary key.

Models with ``allow_tree_view`` and a parent ``ForeignKey`` to self get a **Tree View**
link on the list toolbar (see ``apps.desk.document_tree``).
"""

from django.apps import apps
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import ProtectedError
from django.http import Http404, QueryDict
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.views.generic import ListView

DESK_PAGE_SIZE_OPTIONS = (20, 100, 500, 2500)
_DESK_PAGE_SIZE_SET = frozenset(DESK_PAGE_SIZE_OPTIONS)
DESK_PAGE_SIZE_DEFAULT = 20


def desk_effective_page_size(request) -> int:
    """Validated ``page_size`` from GET (fast path: int parse + set lookup)."""
    raw = request.GET.get('page_size')
    if raw is None:
        return DESK_PAGE_SIZE_DEFAULT
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return DESK_PAGE_SIZE_DEFAULT
    return n if n in _DESK_PAGE_SIZE_SET else DESK_PAGE_SIZE_DEFAULT


def _desk_sort_allowed_field_names(model) -> frozenset[str]:
    from apps.desk.desk_filters import filterable_fields_for_model

    names = {f['name'] for f in filterable_fields_for_model(model)}
    names.add(model._meta.pk.name)
    return frozenset(names)


def desk_sort_field_choices(model) -> list[dict[str, str]]:
    """Dropdown metadata for sort field (filterable fields + PK)."""
    from apps.desk.desk_filters import filterable_fields_for_model

    seen: dict[str, str] = {}
    for f in filterable_fields_for_model(model):
        seen[f['name']] = f['label']
    pk = model._meta.pk
    if pk.name not in seen:
        vn = pk.verbose_name
        seen[pk.name] = str(vn).title() if vn else 'ID'
    rows = [{'name': k, 'label': v} for k, v in seen.items()]
    rows.sort(key=lambda r: (r['label'] or '').lower())
    return rows


def desk_resolved_sort(model, get) -> tuple[str, str]:
    """(field_name, 'asc'|'desc') from GET with safe defaults (matches previous list default)."""
    from apps.desk.registry import default_order_field

    meta = model._meta
    allowed = _desk_sort_allowed_field_names(model)
    raw_f = (get.get('sort') or '').strip()
    raw_d = (get.get('sort_dir') or '').strip().lower()
    if raw_f in allowed:
        if raw_d in ('asc', 'desc'):
            d = raw_d
        else:
            df = default_order_field(model)
            d = 'desc' if raw_f == meta.pk.name and df == meta.pk.name else 'asc'
        return raw_f, d
    df = default_order_field(model)
    if df == meta.pk.name:
        return df, 'desc'
    return df, 'asc'


def desk_order_by_list(model, get) -> list[str]:
    """Arguments for ``QuerySet.order_by`` (stable tie-break on PK when not sorting by PK)."""
    f, d = desk_resolved_sort(model, get)
    meta = model._meta
    prefix = '-' if d == 'desc' else ''
    parts = [f'{prefix}{f}']
    if f != meta.pk.name:
        parts.append(meta.pk.name)
    return parts


def desk_sort_differs_from_default(model, get) -> bool:
    """True when GET carries an explicit sort that is not the default ordering."""
    if not (get.get('sort') or get.get('sort_dir')):
        return False
    empty = QueryDict()
    return desk_resolved_sort(model, get) != desk_resolved_sort(model, empty)


class DeskDocumentListView(LoginRequiredMixin, ListView):
    """Paginated list with row checkboxes and POST bulk delete."""

    template_name = 'desk/document_list.html'
    context_object_name = 'rows'
    paginate_by = DESK_PAGE_SIZE_DEFAULT

    page_title = ''
    page_subtitle = ''
    columns = ()
    admin_url = ''

    def view_perm(self):
        opts = self.model._meta
        return f'{opts.app_label}.view_{opts.model_name}'

    def delete_perm(self):
        opts = self.model._meta
        return f'{opts.app_label}.delete_{opts.model_name}'

    def dispatch(self, request, *args, **kwargs):
        if request.method == 'POST':
            if request.POST.get('desk_bulk_action') == 'delete':
                if not request.user.has_perm(self.delete_perm()):
                    raise PermissionDenied
            else:
                return redirect(self.request.get_full_path())
        elif request.method == 'GET':
            if not request.user.has_perm(self.view_perm()):
                raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if request.POST.get('desk_bulk_action') != 'delete':
            return redirect(request.get_full_path())
        raw_ids = request.POST.getlist('selected')
        if not raw_ids:
            messages.warning(request, 'Select at least one row to delete.')
            return redirect(request.get_full_path())
        qs = self.get_queryset().filter(pk__in=raw_ids)
        try:
            deleted_count, _ = qs.delete()
        except ProtectedError:
            messages.error(
                request,
                'Could not delete one or more rows because other records still reference them.',
            )
            return redirect(request.get_full_path())
        if deleted_count:
            messages.success(
                request,
                f'Deleted {deleted_count} record(s).',
            )
        else:
            messages.warning(request, 'No matching records were deleted.')
        return redirect(request.get_full_path())

    def get_paginate_by(self, queryset):
        return desk_effective_page_size(self.request)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        can_create = False
        document_create_url = None
        if self.model is not None:
            from apps.desk.registry import is_desk_auto_document_model

            if is_desk_auto_document_model(self.model):
                m = self.model._meta
                can_create = self.request.user.has_perm(f'{m.app_label}.add_{m.model_name}')
                if can_create:
                    try:
                        document_create_url = reverse(
                            'desk:document_create',
                            kwargs={'app_label': m.app_label, 'model_name': m.model_name},
                        )
                    except NoReverseMatch:
                        document_create_url = None
        ch = (
            f'{self.model._meta.app_label}.change_{self.model._meta.model_name}'
            if self.model
            else ''
        )
        can_change = bool(self.model and self.request.user.has_perm(ch))
        row_edit_enabled = False
        if self.model and can_change:
            from apps.desk.registry import is_desk_auto_document_model

            row_edit_enabled = is_desk_auto_document_model(self.model)
        desk_tree_view_enabled = False
        desk_tree_view_url = ''
        if self.model is not None:
            from apps.desk.registry import model_allows_tree_view

            if model_allows_tree_view(self.model):
                m = self.model._meta
                desk_tree_view_enabled = True
                try:
                    desk_tree_view_url = reverse(
                        'desk:document_tree',
                        kwargs={'app_label': m.app_label, 'model_name': m.model_name},
                    )
                except NoReverseMatch:
                    desk_tree_view_url = ''
                    desk_tree_view_enabled = False
        sz = desk_effective_page_size(self.request)
        from apps.desk.desk_filters import list_querystring_with_page_size

        desk_page_size_nav = [
            {
                'size': n,
                'href': '?' + list_querystring_with_page_size(self.request.GET, n),
                'active': n == sz,
            }
            for n in DESK_PAGE_SIZE_OPTIONS
        ]
        ctx.update(
            {
                'page_title': self.page_title,
                'page_subtitle': self.page_subtitle,
                'columns': list(self.columns),
                'admin_url': self.admin_url,
                'can_delete': self.request.user.has_perm(self.delete_perm()),
                'can_create': can_create,
                'document_create_url': document_create_url,
                'row_edit_enabled': row_edit_enabled,
                'desk_tree_view_enabled': desk_tree_view_enabled,
                'desk_tree_view_url': desk_tree_view_url,
                'list_model_app': self.model._meta.app_label if self.model else '',
                'list_model_name': self.model._meta.model_name if self.model else '',
                'desk_filters_enabled': False,
                'desk_filter_schema': [],
                'desk_filter_rows': [],
                'desk_filter_errors': [],
                'desk_list_query': '',
                'desk_filter_applied': False,
                'desk_filter_panel_open': False,
                'desk_page_size_options': DESK_PAGE_SIZE_OPTIONS,
                'desk_effective_page_size': sz,
                'desk_page_size_nav': desk_page_size_nav,
                'desk_sort_enabled': False,
                'desk_sort_fields': [],
                'desk_sort_field': '',
                'desk_sort_dir': 'asc',
                'desk_sort_active_dot': False,
                'desk_sort_panel_open': False,
            }
        )
        return ctx


class DeskAutoDocumentListView(DeskDocumentListView):
    """
    Generic list + bulk delete for models registered in ``registry`` auto-discovery
    (``core`` / ``accounts``, excluding ``accounts.User``).
    """

    model = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        app_label = kwargs.get('app_label')
        model_name = kwargs.get('model_name')
        if not app_label or not model_name:
            raise Http404
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError as e:
            raise Http404 from e
        from apps.desk.registry import APP_LABEL_TO_SECTION, auto_columns_for_model, is_desk_auto_document_model

        if not is_desk_auto_document_model(model):
            raise Http404
        self.model = model
        meta = model._meta
        self.page_title = (
            meta.verbose_name_plural.title()
            if meta.verbose_name_plural
            else meta.verbose_name.title()
        )
        self.page_subtitle = APP_LABEL_TO_SECTION.get(meta.app_label, meta.app_label.title())
        self.columns = auto_columns_for_model(model)
        try:
            self.admin_url = reverse(f'admin:{meta.app_label}_{meta.model_name}_changelist')
        except NoReverseMatch:
            self.admin_url = ''

    def get_queryset(self):
        from apps.desk.desk_filters import build_filter_q
        from apps.desk.registry import scope_queryset_by_company

        qs = self.model.objects.all()
        qs = scope_queryset_by_company(qs, self.request.user)
        fq, errors, echo = build_filter_q(self.model, self.request.GET)
        self._desk_filter_errors = errors
        self._desk_filter_echo = echo
        if fq is not None:
            qs = qs.filter(fq)
        return qs.order_by(*desk_order_by_list(self.model, self.request.GET))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.desk.desk_filters import filterable_fields_for_model, preserved_list_querystring

        echo = list(getattr(self, '_desk_filter_echo', ()))
        if not echo:
            rows = [{'field': '', 'op': 'equals', 'val': ''}]
        else:
            rows = echo
        applied = any((r.get('field') or '').strip() for r in rows)
        errs = getattr(self, '_desk_filter_errors', []) or []
        sf, sd = desk_resolved_sort(self.model, self.request.GET)
        sort_open = bool(self.request.GET.get('sort') or self.request.GET.get('sort_dir'))
        ctx.update(
            {
                'desk_filters_enabled': True,
                'desk_filter_schema': filterable_fields_for_model(self.model),
                'desk_filter_rows': rows,
                'desk_filter_errors': errs,
                'desk_list_query': preserved_list_querystring(self.request.GET),
                'desk_filter_applied': applied,
                'desk_filter_panel_open': applied or bool(errs),
                'desk_sort_enabled': True,
                'desk_sort_fields': desk_sort_field_choices(self.model),
                'desk_sort_field': sf,
                'desk_sort_dir': sd,
                'desk_sort_active_dot': desk_sort_differs_from_default(self.model, self.request.GET),
                'desk_sort_panel_open': sort_open,
            }
        )
        return ctx
