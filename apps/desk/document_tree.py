"""
Desk Tree View for hierarchical documents (Frappe / ERPNext–style parent tree).

Resolves structure from a parent ``ForeignKey`` to the same model (e.g.
``parent_account``). Sibling order uses ``lft`` when the model defines nested-set
fields, otherwise label order. Scoped with ``scope_queryset_by_company`` like
list views.
"""

from __future__ import annotations

from collections import defaultdict

from django.apps import apps
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.http import Http404
from django.urls import NoReverseMatch, reverse
from django.views.generic import TemplateView

from apps.desk.registry import (
    APP_LABEL_TO_SECTION,
    desk_tree_parent_field_name,
    is_desk_auto_document_model,
    model_allows_tree_view,
    scope_queryset_by_company,
)


def _model_has_field(model, name: str) -> bool:
    try:
        model._meta.get_field(name)
        return True
    except FieldDoesNotExist:
        return False


_TREE_LABEL_FALLBACKS = (
    'account_name',
    'cost_center_name',
    'name',
    'title',
    'slug',
    'email',
)


def desk_tree_label_for(obj) -> str:
    model = obj.__class__
    explicit = getattr(model, 'desk_tree_label_field', None)
    if explicit:
        v = getattr(obj, explicit, None)
        if v is not None and str(v).strip():
            return str(v)
    for n in _TREE_LABEL_FALLBACKS:
        if not _model_has_field(model, n):
            continue
        v = getattr(obj, n, None)
        if v is not None and str(v).strip():
            return str(v)
    return str(obj.pk)


def desk_tree_subtitle_for(obj) -> str:
    model = obj.__class__
    for num_field in ('account_number', 'cost_center_number', 'code'):
        if not _model_has_field(model, num_field):
            continue
        v = getattr(obj, num_field, None)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ''


def build_desk_tree_nodes(queryset, model, parent_field: str, user):
    """
    Nested list of dicts: pk, label, subtitle, edit_url, is_group, disabled, children.
    """
    rows = list(queryset)
    ids = {obj.pk for obj in rows}
    accessor = f'{parent_field}_id'
    by_parent = defaultdict(list)
    for obj in rows:
        pid = getattr(obj, accessor)
        if pid is not None and pid not in ids:
            pid = None
        by_parent[pid].append(obj)

    has_lft = _model_has_field(model, 'lft')
    has_is_group = _model_has_field(model, 'is_group')
    has_disabled = _model_has_field(model, 'disabled')
    meta = model._meta
    can_change = user.has_perm(f'{meta.app_label}.change_{meta.model_name}')

    def sort_key(o):
        lft = getattr(o, 'lft', 0) if has_lft else 0
        return (lft, desk_tree_label_for(o).lower())

    def build(parent_id):
        chunk = list(by_parent.get(parent_id, []))
        chunk.sort(key=sort_key)
        out = []
        for obj in chunk:
            children = build(obj.pk)
            edit_url = None
            if can_change:
                try:
                    edit_url = reverse(
                        'desk:document_change',
                        kwargs={
                            'app_label': meta.app_label,
                            'model_name': meta.model_name,
                            'pk': obj.pk,
                        },
                    )
                except NoReverseMatch:
                    pass
            is_group = bool(getattr(obj, 'is_group', False)) if has_is_group else bool(children)
            disabled = bool(getattr(obj, 'disabled', False)) if has_disabled else False
            out.append(
                {
                    'pk': obj.pk,
                    'label': desk_tree_label_for(obj),
                    'subtitle': desk_tree_subtitle_for(obj),
                    'edit_url': edit_url,
                    'is_group': is_group,
                    'disabled': disabled,
                    'children': children,
                }
            )
        return out

    root_list = build(None)
    if not root_list and rows:
        flat = []
        for obj in sorted(rows, key=sort_key):
            edit_url = None
            if can_change:
                try:
                    edit_url = reverse(
                        'desk:document_change',
                        kwargs={
                            'app_label': meta.app_label,
                            'model_name': meta.model_name,
                            'pk': obj.pk,
                        },
                    )
                except NoReverseMatch:
                    pass
            flat.append(
                {
                    'pk': obj.pk,
                    'label': desk_tree_label_for(obj),
                    'subtitle': desk_tree_subtitle_for(obj),
                    'edit_url': edit_url,
                    'is_group': bool(getattr(obj, 'is_group', False)) if has_is_group else False,
                    'disabled': bool(getattr(obj, 'disabled', False)) if has_disabled else False,
                    'children': [],
                }
            )
        return flat
    return root_list


class DeskAutoDocumentTreeView(LoginRequiredMixin, TemplateView):
    template_name = 'desk/document_tree.html'

    model = None

    def view_perm(self):
        opts = self.model._meta
        return f'{opts.app_label}.view_{opts.model_name}'

    def dispatch(self, request, *args, **kwargs):
        app_label = kwargs.get('app_label')
        model_name = kwargs.get('model_name')
        if not app_label or not model_name:
            raise Http404
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError as e:
            raise Http404 from e
        if not is_desk_auto_document_model(model) or not model_allows_tree_view(model):
            raise Http404
        self.model = model
        if not request.user.has_perm(self.view_perm()):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        meta = self.model._meta
        parent_field = desk_tree_parent_field_name(self.model)
        assert parent_field is not None

        qs = self.model.objects.all()
        qs = scope_queryset_by_company(qs, self.request.user)
        sel_related = [parent_field]
        if _model_has_field(self.model, 'company'):
            sel_related.append('company')
        qs = qs.select_related(*sel_related)

        tree_nodes = build_desk_tree_nodes(qs, self.model, parent_field, self.request.user)

        page_title = (
            meta.verbose_name_plural.title()
            if meta.verbose_name_plural
            else meta.verbose_name.title()
        )
        try:
            document_list_url = reverse(
                'desk:document_list',
                kwargs={'app_label': meta.app_label, 'model_name': meta.model_name},
            )
        except NoReverseMatch:
            document_list_url = '#'
        try:
            admin_url = reverse(f'admin:{meta.app_label}_{meta.model_name}_changelist')
        except NoReverseMatch:
            admin_url = ''

        ctx.update(
            {
                'page_title': page_title,
                'page_subtitle': APP_LABEL_TO_SECTION.get(meta.app_label, meta.app_label.title()),
                'tree_nodes': tree_nodes,
                'document_list_url': document_list_url,
                'admin_url': admin_url,
                'list_model_app': meta.app_label,
                'list_model_name': meta.model_name,
                'tree_parent_field': parent_field,
            }
        )
        return ctx
