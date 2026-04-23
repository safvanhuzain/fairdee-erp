"""Shared permission-matrix rows + selected ids for desk forms (User, Group, …)."""

from apps.desk.registry import permission_queryset_for_user_matrix
from apps.desk.user_create_ui import build_permission_rows


def permission_matrix_rows():
    return build_permission_rows(permission_queryset_for_user_matrix())


def desk_permission_matrix_context(request, field_name, selected_ids_from_instance=None):
    """
    ``field_name``: POST key for checkboxes (e.g. ``user_permissions`` or ``permissions``).
    ``selected_ids_from_instance``: optional iterable of permission pks (e.g. group.permissions).
    """
    rows = permission_matrix_rows()
    if request.method == 'POST':
        selected = [int(x) for x in request.POST.getlist(field_name) if str(x).isdigit()]
    elif selected_ids_from_instance is not None:
        selected = list(selected_ids_from_instance)
    else:
        selected = []
    return {
        'permission_rows': rows,
        'selected_perm_pks': selected,
        'matrix_field_name': field_name,
    }
