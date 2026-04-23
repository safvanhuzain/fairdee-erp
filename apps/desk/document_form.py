"""
Generic desk "new document" form for auto-discovered models (core / accounts / auth.Group).

``auth.Group`` uses ``DeskGroupForm`` + the same permission matrix as the Users
create flow. Other models use a dynamic ``ModelForm`` with ``fields = '__all__'``.
"""

from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps.desk.forms import DeskDataImportForm, DeskGroupForm
from apps.desk.permission_matrix import desk_permission_matrix_context


def _is_auth_group(model):
    return model._meta.label_lower == 'auth.group'


def _is_desk_dataimport(model):
    return model._meta.label_lower == 'desk.dataimport'


def _data_import_create_context(view, form):
    meta = view.model._meta
    plural = (
        meta.verbose_name_plural.title()
        if meta.verbose_name_plural
        else meta.verbose_name.title()
    )
    return {
        'form': form,
        'page_title': view.page_title,
        'page_subtitle': view.page_subtitle,
        'list_url': view.list_url,
        'doctype_plural': plural,
        'submit_label': 'Start import',
    }


def _data_import_detail_context(view):
    meta = view.model._meta
    plural = (
        meta.verbose_name_plural.title()
        if meta.verbose_name_plural
        else meta.verbose_name.title()
    )
    obj = view.object
    return {
        'import_obj': obj,
        'page_title': f'Import #{obj.pk}',
        'page_subtitle': view.page_subtitle,
        'list_url': view.list_url,
        'doctype_plural': plural,
        'error_report': obj.error_report or [],
    }


def _style_model_form_widgets(form):
    for _name, field in form.fields.items():
        w = field.widget
        if isinstance(w, forms.CheckboxInput):
            w.attrs.setdefault('class', 'desk-table__check-input')
        elif isinstance(w, forms.Select):
            w.attrs.setdefault('class', 'desk-modal-select')
        elif isinstance(w, forms.Textarea):
            w.attrs.setdefault('class', 'desk-modal-input')
            w.attrs.setdefault('rows', min(int(w.attrs.get('rows', 4)), 12))
        elif isinstance(w, (forms.ClearableFileInput, forms.FileInput)):
            w.attrs.setdefault('class', 'desk-modal-input')
        else:
            w.attrs.setdefault('class', 'desk-modal-input')


def _desk_blank_select_empty_labels(form):
    """Optional FKs: empty first choice label blank instead of Django's '---------'."""
    for field in form.fields.values():
        if isinstance(field, forms.ModelMultipleChoiceField):
            continue
        if isinstance(field, forms.ModelChoiceField) and field.empty_label is not None:
            field.empty_label = ''
        elif isinstance(field, forms.ChoiceField) and not isinstance(
            field, (forms.ModelChoiceField, forms.ModelMultipleChoiceField)
        ):
            try:
                choices = list(field.choices)
            except (TypeError, ValueError):
                continue
            changed = False
            new_choices = []
            for row in choices:
                if isinstance(row, (list, tuple)) and len(row) == 2 and isinstance(row[1], (list, tuple)):
                    new_choices.append(row)
                    continue
                if isinstance(row, (list, tuple)) and len(row) >= 2:
                    val, lab = row[0], row[1]
                    if val in ('', None) and str(lab) == '---------':
                        new_choices.append((val, ''))
                        changed = True
                        continue
                new_choices.append(row)
            if changed:
                field.choices = new_choices


def _desk_model_modelform_factory(model, user):
    """One ModelForm subclass per call; used for desk create and edit."""
    meta = model._meta
    target_model = model

    class DeskModelForm(forms.ModelForm):
        class Meta:
            model = target_model
            fields = '__all__'

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            _style_model_form_widgets(self)
            _desk_blank_select_empty_labels(self)
            if not user.is_superuser and getattr(user, 'company_id', None):
                try:
                    meta.get_field('company')
                    co = apps.get_model('core', 'Company')
                    qs = co.objects.filter(pk=user.company_id)
                    if 'company' in self.fields:
                        self.fields['company'].queryset = qs
                    if qs.count() == 1 and not self.instance.pk:
                        self.initial.setdefault('company', user.company_id)
                except (FieldDoesNotExist, KeyError):
                    pass

    return DeskModelForm


def build_desk_create_form(model, user, data=None, files=None):
    """Build a ModelForm for a new *model* instance."""
    Form = _desk_model_modelform_factory(model, user)
    kwargs = {}
    if data is not None:
        kwargs['data'] = data
    if files is not None:
        kwargs['files'] = files
    return Form(**kwargs)


def build_desk_edit_form(model, user, instance, data=None, files=None):
    """Build a ModelForm bound to *instance* (same field styling and company FK scoping as create)."""
    Form = _desk_model_modelform_factory(model, user)
    kwargs = {'instance': instance}
    if data is not None:
        kwargs['data'] = data
    if files is not None:
        kwargs['files'] = files
    return Form(**kwargs)


def _scope_create_instance(obj, user, model):
    """Force company FK for non-superusers when the model has one (matches list scoping)."""
    if user.is_superuser or not getattr(user, 'company_id', None):
        return
    try:
        model._meta.get_field('company')
    except FieldDoesNotExist:
        return
    setattr(obj, 'company_id', user.company_id)


def _apply_fk_defaults(obj, user):
    """Set created_by (and similar) when the field exists and is empty."""
    if not getattr(user, 'is_authenticated', False):
        return
    meta = obj._meta
    for name in ('created_by', 'updated_by'):
        try:
            f = meta.get_field(name)
        except FieldDoesNotExist:
            continue
        if not f.is_relation or f.many_to_many:
            continue
        if getattr(obj, f.attname, None) is None:
            rel = getattr(f.remote_field, 'model', None)
            if rel and isinstance(user, rel):
                setattr(obj, name, user)


def _apply_updated_by(obj, user):
    """On save of an existing row, set updated_by when the FK exists and points at the user model."""
    if not getattr(user, 'is_authenticated', False) or not obj.pk:
        return
    try:
        f = obj._meta.get_field('updated_by')
    except FieldDoesNotExist:
        return
    if not f.is_relation or f.many_to_many:
        return
    rel = getattr(f.remote_field, 'model', None)
    if rel and isinstance(user, rel):
        setattr(obj, 'updated_by', user)


def _group_page_context(model, list_url, page_title, submit_label, form, page_subtitle):
    meta = model._meta
    plural = (
        meta.verbose_name_plural.title()
        if meta.verbose_name_plural
        else meta.verbose_name.title()
    )
    return {
        'form': form,
        'page_title': page_title,
        'page_subtitle': page_subtitle,
        'list_url': list_url,
        'doctype_plural': plural,
        'submit_label': submit_label,
    }


class DeskAutoDocumentCreateView(LoginRequiredMixin, View):
    template_name = 'desk/document_form.html'

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
        from apps.desk.registry import APP_LABEL_TO_SECTION, is_desk_auto_document_model

        if not is_desk_auto_document_model(model):
            raise Http404
        self.model = model
        self._app_label = app_label
        self._model_name = model_name
        meta = model._meta
        self.page_title = f"New {meta.verbose_name.title()}"
        self.page_subtitle = APP_LABEL_TO_SECTION.get(meta.app_label, meta.app_label.title())
        self.list_url = reverse('desk:document_list', kwargs={'app_label': app_label, 'model_name': model_name})

    def add_perm(self):
        m = self.model._meta
        return f'{m.app_label}.add_{m.model_name}'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_perm(self.add_perm()):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def _context(self, form):
        meta = self.model._meta
        plural = (
            meta.verbose_name_plural.title()
            if meta.verbose_name_plural
            else meta.verbose_name.title()
        )
        return {
            'form': form,
            'page_title': self.page_title,
            'page_subtitle': self.page_subtitle,
            'list_url': self.list_url,
            'doctype_plural': plural,
        }

    def get(self, request, *args, **kwargs):
        if _is_auth_group(self.model):
            form = DeskGroupForm()
            ctx = _group_page_context(
                self.model,
                self.list_url,
                self.page_title,
                'Create group',
                form,
                self.page_subtitle,
            )
            ctx.update(desk_permission_matrix_context(request, 'permissions'))
            return render(request, 'desk/group_form.html', ctx)
        if _is_desk_dataimport(self.model):
            form = DeskDataImportForm(request.user)
            return render(request, 'desk/data_import_form.html', _data_import_create_context(self, form))
        form = build_desk_create_form(self.model, request.user)
        return render(request, self.template_name, self._context(form))

    def post(self, request, *args, **kwargs):
        if _is_auth_group(self.model):
            form = DeskGroupForm(request.POST)
            ctx = _group_page_context(
                self.model,
                self.list_url,
                self.page_title,
                'Create group',
                form,
                self.page_subtitle,
            )
            ctx.update(desk_permission_matrix_context(request, 'permissions'))
            if form.is_valid():
                group = form.save()
                messages.success(request, f'Group "{group.name}" was created.')
                return redirect(self.list_url)
            return render(request, 'desk/group_form.html', ctx)
        if _is_desk_dataimport(self.model):
            from apps.desk.import_service import run_data_import
            from apps.desk.models import DataImport

            form = DeskDataImportForm(request.user, request.POST, request.FILES)
            if form.is_valid():
                cd = form.cleaned_data
                di = DataImport(
                    content_type=cd['content_type'],
                    mode=cd['mode'],
                    attachment=cd['attachment'],
                    status=DataImport.Status.PENDING,
                    created_by=request.user,
                )
                if getattr(request.user, 'company_id', None) and not request.user.is_superuser:
                    di.company_id = request.user.company_id
                di.save()
                run_data_import(di, request.user)
                messages.success(
                    request,
                    f'Import finished: {di.rows_created} created, {di.rows_updated} updated, {di.rows_failed} failed.',
                )
                return redirect(
                    reverse(
                        'desk:document_change',
                        kwargs={
                            'app_label': self._app_label,
                            'model_name': self._model_name,
                            'pk': di.pk,
                        },
                    )
                )
            return render(request, 'desk/data_import_form.html', _data_import_create_context(self, form))
        form = build_desk_create_form(self.model, request.user, data=request.POST, files=request.FILES)
        if form.is_valid():
            obj = form.save(commit=False)
            _scope_create_instance(obj, request.user, self.model)
            _apply_fk_defaults(obj, request.user)
            obj.save()
            form.save_m2m()
            messages.success(request, f'{obj} was saved.')
            return redirect(self.list_url)
        return render(request, self.template_name, self._context(form))


class DeskAutoDocumentUpdateView(LoginRequiredMixin, View):
    """
    Edit any auto-discovered desk document.

    ``auth.Group`` uses ``DeskGroupForm`` + ``group_form.html`` (permission matrix).
    Other models use the same dynamic ``ModelForm`` as create.
    """

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        app_label = kwargs.get('app_label')
        model_name = kwargs.get('model_name')
        pk = kwargs.get('pk')
        if not app_label or not model_name or pk is None:
            raise Http404
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError as e:
            raise Http404 from e
        from apps.desk.registry import APP_LABEL_TO_SECTION, is_desk_auto_document_model, scope_queryset_by_company

        if not is_desk_auto_document_model(model):
            raise Http404
        self.model = model
        qs = scope_queryset_by_company(model.objects.all(), request.user)
        self.object = get_object_or_404(qs, pk=pk)
        self.list_url = reverse('desk:document_list', kwargs={'app_label': app_label, 'model_name': model_name})
        if _is_auth_group(model):
            self.page_title = f'Edit {self.object.name}'
        else:
            self.page_title = f'Edit {self.object}'
        self.page_subtitle = APP_LABEL_TO_SECTION.get(
            model._meta.app_label, model._meta.app_label.title()
        )
        self._app_label = app_label
        self._model_name = model_name

    def change_perm(self):
        m = self.model._meta
        return f'{m.app_label}.change_{m.model_name}'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_perm(self.change_perm()):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def _generic_form_context(self, form):
        meta = self.model._meta
        plural = (
            meta.verbose_name_plural.title()
            if meta.verbose_name_plural
            else meta.verbose_name.title()
        )
        return {
            'form': form,
            'page_title': self.page_title,
            'page_subtitle': self.page_subtitle,
            'list_url': self.list_url,
            'doctype_plural': plural,
        }

    def get(self, request, *args, **kwargs):
        if _is_auth_group(self.model):
            form = DeskGroupForm(instance=self.object)
            ctx = _group_page_context(
                self.model,
                self.list_url,
                self.page_title,
                'Save',
                form,
                self.page_subtitle,
            )
            ctx.update(
                desk_permission_matrix_context(
                    request,
                    'permissions',
                    self.object.permissions.values_list('pk', flat=True),
                )
            )
            return render(request, 'desk/group_form.html', ctx)
        if _is_desk_dataimport(self.model):
            return render(request, 'desk/data_import_detail.html', _data_import_detail_context(self))
        form = build_desk_edit_form(self.model, request.user, self.object)
        return render(request, 'desk/document_form.html', self._generic_form_context(form))

    def post(self, request, *args, **kwargs):
        if _is_auth_group(self.model):
            form = DeskGroupForm(request.POST, instance=self.object)
            ctx = _group_page_context(
                self.model,
                self.list_url,
                self.page_title,
                'Save',
                form,
                self.page_subtitle,
            )
            ctx.update(desk_permission_matrix_context(request, 'permissions'))
            if form.is_valid():
                group = form.save()
                messages.success(request, f'Group "{group.name}" was updated.')
                return redirect(self.list_url)
            return render(request, 'desk/group_form.html', ctx)
        if _is_desk_dataimport(self.model):
            messages.info(request, 'Import records are read-only.')
            return redirect(
                reverse(
                    'desk:document_change',
                    kwargs={
                        'app_label': self._app_label,
                        'model_name': self._model_name,
                        'pk': self.object.pk,
                    },
                )
            )
        form = build_desk_edit_form(
            self.model, request.user, self.object, data=request.POST, files=request.FILES
        )
        if form.is_valid():
            obj = form.save(commit=False)
            _scope_create_instance(obj, request.user, self.model)
            _apply_updated_by(obj, request.user)
            obj.save()
            form.save_m2m()
            messages.success(request, f'{obj} was updated.')
            return redirect(self.list_url)
        return render(request, 'desk/document_form.html', self._generic_form_context(form))
