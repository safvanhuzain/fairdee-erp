"""
Desk document registry: nav, home cards, and create-user permission matrix.

**Core**, **Accounts**, **Finance**, **Desk** (e.g. data imports), and **Django auth Group**
are discovered automatically from installed models (see ``DESK_AUTO_APP_LABELS`` /
``DESK_AUTO_DOCUMENT_EXCLUDE``). Each gets the same list + create UI via
``DeskAutoDocumentListView`` / ``DeskAutoDocumentCreateView``.

CSV import targets are models with ``allow_bulk_upload = True`` (or listed in
``BULK_UPLOAD_BY_LABEL``); see ``content_types_for_bulk_upload``.

Models may set ``allow_tree_view = True`` plus a single ``ForeignKey`` to ``self``
(or ``desk_tree_parent_field`` when there are multiple self-FKs) to enable the
desk **Tree View** (parent / children, same company scope as list).

``accounts.User`` is excluded here because it uses ``DeskUserListView`` (invite
modal, etc.). ``auth.Permission`` is excluded (not a desk document). Add other
exclusions if a model needs a custom desk page.
"""

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.db.models import BinaryField, ForeignKey
from django.urls import NoReverseMatch, reverse

from apps.access.models import RoleProfile

User = get_user_model()

# Apps whose concrete (non-proxy) models get a desk list + nav entry (unless excluded).
DESK_AUTO_APP_LABELS = ('core', 'accounts', 'auth', 'finance', 'desk')
# (app_label, model_name) — use default list view / nav elsewhere.
DESK_AUTO_DOCUMENT_EXCLUDE = {
    ('accounts', 'user'),
    ('auth', 'permission'),
    ('auth', 'user'),
    # Finance: operational docs stay excluded; Account / CostCenter use the desk.
    ('finance', 'invoice'),
    ('finance', 'purchaseinvoice'),
    ('finance', 'journalentry'),
    ('finance', 'journalline'),
}

APP_LABEL_TO_SECTION = {
    'core': 'Core',
    'accounts': 'Accounts',
    'auth': 'Accounts',
    'finance': 'Finance',
    'desk': 'Desk',
}

# Models without a class attribute can still allow CSV import (e.g. django.contrib.auth).
BULK_UPLOAD_BY_LABEL = frozenset(
    {
        'auth.group',
    }
)

_desk_documents_cache = None


def model_allows_bulk_upload(model) -> bool:
    """True if desk CSV import may target this model (``allow_bulk_upload`` or registry allowlist)."""
    meta = model._meta
    if getattr(model, 'allow_bulk_upload', False):
        return True
    return meta.label_lower in BULK_UPLOAD_BY_LABEL


def content_types_for_bulk_upload():
    """ContentType rows for models that may receive CSV imports."""
    cts = []
    for ct in ContentType.objects.order_by('app_label', 'model'):
        m = ct.model_class()
        if m is None:
            continue
        if not model_allows_bulk_upload(m):
            continue
        cts.append(ct.pk)
    return ContentType.objects.filter(pk__in=cts).order_by('app_label', 'model')


def is_desk_auto_document_model(model):
    """True if this model should use the generic desk document list + nav."""
    meta = model._meta
    if meta.abstract or meta.proxy:
        return False
    if meta.app_label not in DESK_AUTO_APP_LABELS:
        return False
    if (meta.app_label, meta.model_name) in DESK_AUTO_DOCUMENT_EXCLUDE:
        return False
    return True


def desk_tree_parent_field_name(model):
    """
    Field name of the parent pointer for tree view (Frappe-style parent/children).

    Uses ``desk_tree_parent_field`` when set; otherwise the sole ``ForeignKey`` to
    ``self`` on the model. Returns ``None`` if ambiguous (multiple self-FKs).
    """
    explicit = getattr(model, 'desk_tree_parent_field', None)
    if explicit:
        try:
            f = model._meta.get_field(explicit)
        except FieldDoesNotExist:
            return None
        if isinstance(f, ForeignKey) and f.remote_field.model == model:
            return explicit
        return None
    names = []
    for f in model._meta.fields:
        if isinstance(f, ForeignKey) and f.remote_field.model == model:
            names.append(f.name)
    if len(names) == 1:
        return names[0]
    return None


def model_allows_tree_view(model) -> bool:
    """True when desk should offer Tree View for this model (list + tree URLs)."""
    if not getattr(model, 'allow_tree_view', False):
        return False
    return desk_tree_parent_field_name(model) is not None


def _iter_auto_models(app_label):
    for model in apps.get_app_config(app_label).get_models():
        if is_desk_auto_document_model(model):
            yield model


def auto_columns_for_model(model):
    """First few concrete fields as list columns (password omitted)."""
    cols = []
    for f in model._meta.fields:
        if f.name in ('password',):
            continue
        if isinstance(f, BinaryField):
            continue
        cols.append({'key': f.name, 'label': f.verbose_name.title()})
        if len(cols) >= 7:
            break
    if not cols:
        cols.append({'key': model._meta.pk.name, 'label': 'ID'})
    return tuple(cols)


def scope_queryset_by_company(qs, user):
    """Limit rows to the user's company when the model (or Company row) supports it."""
    if user.is_superuser or not getattr(user, 'company_id', None):
        return qs
    model = qs.model
    meta = model._meta
    if meta.app_label == 'core' and meta.model_name == 'company':
        return qs.filter(pk=user.company_id)
    try:
        meta.get_field('company')
        return qs.filter(company_id=user.company_id)
    except FieldDoesNotExist:
        return qs


def default_order_field(model):
    meta = model._meta
    for name in ('name', 'slug', 'title', 'email'):
        try:
            meta.get_field(name)
            return name
        except Exception:
            pass
    return meta.pk.name


def _doc_for_model(model):
    meta = model._meta
    label = (
        meta.verbose_name_plural.title()
        if meta.verbose_name_plural
        else meta.verbose_name.title()
    )
    kwargs = {'app_label': meta.app_label, 'model_name': meta.model_name}
    try:
        href = reverse('desk:document_list', kwargs=kwargs)
    except NoReverseMatch:
        href = '#'
    return {
        'model': model,
        'label': label,
        'section': APP_LABEL_TO_SECTION.get(meta.app_label, meta.app_label.title()),
        'href': href,
        'nav_url_name': 'document_list',
        'nav_app_label': meta.app_label,
        'nav_model_name': meta.model_name,
    }


def _doc_for_user_list():
    try:
        href = reverse('desk:user_list')
    except NoReverseMatch:
        href = '#'
    return {
        'model': User,
        'label': 'Users',
        'section': APP_LABEL_TO_SECTION.get('accounts', 'Accounts'),
        'href': href,
        'nav_url_name': 'user_list',
        'nav_app_label': None,
        'nav_model_name': None,
    }


def _build_desk_documents():
    out = []
    for app_label in DESK_AUTO_APP_LABELS:
        models = sorted(_iter_auto_models(app_label), key=lambda m: m._meta.model_name)
        if app_label == 'accounts':
            out.append(_doc_for_user_list())
        for model in models:
            if model._meta.model_name == 'user':
                continue
            out.append(_doc_for_model(model))
    return out


def get_desk_documents():
    """Cached list of nav/home/matrix document descriptors."""
    global _desk_documents_cache
    if _desk_documents_cache is None:
        _desk_documents_cache = _build_desk_documents()
    return _desk_documents_cache


def _view_perm(model):
    opts = model._meta
    return f'{opts.app_label}.view_{opts.model_name}'


def get_desk_nav_sections(user):
    """Grouped nav entries the user may open (has view permission)."""
    index_by_section = {}
    sections = []
    for doc in get_desk_documents():
        if not user.has_perm(_view_perm(doc['model'])):
            continue
        sec = doc['section']
        if sec not in index_by_section:
            index_by_section[sec] = len(sections)
            sections.append({'label': sec, 'items': []})
        sections[index_by_section[sec]]['items'].append(doc)
    return sections


def get_desk_documents_catalog(user):
    """All registered desk documents with access flag (for home cards)."""
    catalog = []
    for doc in get_desk_documents():
        perm = _view_perm(doc['model'])
        catalog.append(
            {
                **doc,
                'view_perm': perm,
                'has_access': user.has_perm(perm),
            }
        )
    return catalog


def matrix_permission_models():
    """Models whose permissions appear in the create-user matrix."""
    models = {User, Group, RoleProfile}
    for doc in get_desk_documents():
        models.add(doc['model'])
    return models


def permission_queryset_for_user_matrix():
    """Permissions limited to registry-backed models + auth helpers."""
    cts = ContentType.objects.get_for_models(*matrix_permission_models(), for_concrete_models=True)
    ct_list = list(cts.values())
    from django.contrib.auth.models import Permission

    return (
        Permission.objects.filter(content_type__in=ct_list)
        .select_related('content_type')
        .order_by('content_type__app_label', 'content_type__model', 'codename')
    )
