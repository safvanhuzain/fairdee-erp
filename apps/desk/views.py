import re

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import ProtectedError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import TemplateView

from apps.desk.import_service import (
    build_template_csv_bytes,
    template_field_rows_for_model,
    validate_template_field_names,
)
from apps.desk.registry import content_types_for_bulk_upload

from apps.desk.forms import DeskUserCreateForm, EmailAuthenticationForm
User = get_user_model()


def _desk_user_create_extras(request, create_form):
    """Context for custom groups grid + permission-by-model matrix in the create-user modal."""
    if create_form is None:
        return {}
    from django.contrib.auth.models import Group

    from apps.desk.registry import permission_queryset_for_user_matrix
    from apps.desk.user_create_ui import build_permission_rows

    perms_qs = permission_queryset_for_user_matrix()
    permission_rows = build_permission_rows(perms_qs)
    all_groups = list(Group.objects.order_by('name'))
    selected_group_pks = []
    selected_perm_pks = []
    if request.method == 'POST':
        selected_group_pks = [int(x) for x in request.POST.getlist('groups') if str(x).isdigit()]
        selected_perm_pks = [int(x) for x in request.POST.getlist('user_permissions') if str(x).isdigit()]
    return {
        'permission_rows': permission_rows,
        'all_groups': all_groups,
        'selected_group_pks': selected_group_pks,
        'selected_perm_pks': selected_perm_pks,
    }


class DeskLoginView(LoginView):
    template_name = 'desk/login.html'
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True


class DeskHomeView(LoginRequiredMixin, TemplateView):
    template_name = 'desk/home.html'


class DeskUserListView(LoginRequiredMixin, View):
    """List users; POST creates a user (requires accounts.add_user)."""

    template_name = 'desk/user_list.html'

    def dispatch(self, request, *args, **kwargs):
        if request.method == 'POST':
            if request.POST.get('desk_bulk_action') == 'delete':
                if not request.user.has_perm('accounts.delete_user'):
                    raise PermissionDenied
            elif not request.user.has_perm('accounts.add_user'):
                raise PermissionDenied
        elif request.method == 'GET' and not request.user.has_perm('accounts.view_user'):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_user_queryset(self):
        qs = User.objects.select_related('company').prefetch_related('groups').order_by('email')
        if getattr(self.request.user, 'company_id', None) and not self.request.user.is_superuser:
            qs = qs.filter(company_id=self.request.user.company_id)
        return qs

    def get(self, request):
        users = self.get_user_queryset()
        create_form = DeskUserCreateForm(request.user) if request.user.has_perm('accounts.add_user') else None
        ctx = {
            'users': users,
            'create_form': create_form,
            'can_delete': request.user.has_perm('accounts.delete_user'),
        }
        ctx.update(_desk_user_create_extras(request, create_form))
        return render(request, self.template_name, ctx)

    def post_bulk_delete(self, request):
        raw_ids = request.POST.getlist('selected')
        ids = [int(x) for x in raw_ids if str(x).isdigit()]
        if not ids:
            messages.warning(request, 'Select at least one row to delete.')
            return redirect('desk:user_list')
        qs = self.get_user_queryset().filter(pk__in=ids).exclude(pk=request.user.pk)
        if not request.user.is_superuser:
            qs = qs.filter(is_superuser=False)
        try:
            deleted_count, _ = qs.delete()
        except ProtectedError:
            messages.error(
                request,
                'Could not delete one or more users because other records still reference them.',
            )
            return redirect('desk:user_list')
        if deleted_count:
            messages.success(request, f'Deleted {deleted_count} user(s).')
        else:
            messages.warning(request, 'No matching users were deleted.')
        return redirect('desk:user_list')

    def post(self, request):
        if request.POST.get('desk_bulk_action') == 'delete':
            return self.post_bulk_delete(request)
        users = self.get_user_queryset()
        create_form = DeskUserCreateForm(request.user, request.POST)
        if create_form.is_valid():
            cd = create_form.cleaned_data
            extra = {}
            if 'company' in create_form.fields:
                extra['company'] = cd['company']
            elif getattr(request.user, 'company_id', None) and not request.user.is_superuser:
                extra['company_id'] = request.user.company_id
            user = User.objects.create_user(
                email=cd['email'],
                password=cd['password1'],
                **extra,
            )
            user.groups.set(cd['groups'])
            user.user_permissions.set(cd['user_permissions'])
            messages.success(request, f'User {user.email} was created successfully.')
            return redirect('desk:user_list')
        ctx = {
            'users': users,
            'create_form': create_form,
            'can_delete': request.user.has_perm('accounts.delete_user'),
        }
        ctx.update(_desk_user_create_extras(request, create_form))
        return render(request, self.template_name, ctx)


def _resolve_bulk_upload_target(request, ct_id_raw):
    """
    Resolve ContentType + model for CSV template APIs.
    Returns ``((ct, model), None)`` or ``(None, JsonResponse)`` on error.
    """
    if ct_id_raw is None or str(ct_id_raw).strip() == '':
        return None, JsonResponse({'error': 'content_type_id required'}, status=400)
    try:
        ct_id = int(ct_id_raw)
    except (TypeError, ValueError):
        return None, JsonResponse({'error': 'invalid content_type_id'}, status=400)
    try:
        ct = ContentType.objects.get(pk=ct_id)
    except ContentType.DoesNotExist:
        return None, JsonResponse({'error': 'unknown content type'}, status=404)
    if not content_types_for_bulk_upload().filter(pk=ct.pk).exists():
        return None, JsonResponse({'error': 'model does not allow bulk upload'}, status=403)
    model = ct.model_class()
    if model is None:
        return None, JsonResponse({'error': 'model not loaded'}, status=400)
    add_perm = f'{model._meta.app_label}.add_{model._meta.model_name}'
    if not request.user.has_perm(add_perm):
        return None, JsonResponse({'error': 'permission denied'}, status=403)
    return (ct, model), None


class DeskDataImportTemplateFieldsView(LoginRequiredMixin, View):
    """JSON list of importable fields for a ContentType (for the template modal)."""

    def get(self, request):
        resolved, err = _resolve_bulk_upload_target(request, request.GET.get('content_type_id'))
        if err:
            return err
        _ct, model = resolved
        fields = template_field_rows_for_model(model)
        return JsonResponse({'fields': fields})


class DeskDataImportTemplateDownloadView(LoginRequiredMixin, View):
    """POST selected field names → CSV header row only (UTF-8 BOM)."""

    def post(self, request):
        resolved, err = _resolve_bulk_upload_target(request, request.POST.get('content_type_id'))
        if err:
            return err
        _ct, model = resolved
        names = request.POST.getlist('fields')
        columns, err_msg = validate_template_field_names(model, names)
        if err_msg:
            return JsonResponse({'error': err_msg}, status=400)
        body = build_template_csv_bytes(columns)
        slug = re.sub(r'[^\w\-.]+', '_', model._meta.label_lower)
        fname = f'import_template_{slug}.csv'
        resp = HttpResponse(body, content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = f'attachment; filename="{fname}"'
        return resp
