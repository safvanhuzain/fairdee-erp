"""
Layout helpers for desk "Create user" — permissions grouped by model (Add/Change/Delete/View columns).
"""

from collections import defaultdict


def _bucket_codename(codename):
    if codename.startswith('add_'):
        return 'add'
    if codename.startswith('change_'):
        return 'change'
    if codename.startswith('delete_'):
        return 'delete'
    if codename.startswith('view_'):
        return 'view'
    return None


def build_permission_rows(permissions_qs):
    """
    One table row per content type; columns add / change / delete / view + extras.
    `permissions_qs` should be evaluated queryset with select_related('content_type').
    """
    by_ct = defaultdict(list)
    for p in permissions_qs:
        by_ct[p.content_type_id].append(p)

    rows = []
    for ct_id in sorted(
        by_ct.keys(),
        key=lambda i: (by_ct[i][0].content_type.app_label, by_ct[i][0].content_type.model),
    ):
        plist = by_ct[ct_id]
        ct = plist[0].content_type
        model_cls = ct.model_class()
        if model_cls is not None:
            verbose = model_cls._meta.verbose_name.title()
        else:
            verbose = ct.model.replace('_', ' ').title()
        label = f'{ct.app_label} · {verbose}'

        buckets = {'add': None, 'change': None, 'delete': None, 'view': None}
        extras = []
        for p in plist:
            b = _bucket_codename(p.codename)
            if b in buckets:
                if buckets[b] is None:
                    buckets[b] = p
                else:
                    extras.append(p)
            else:
                extras.append(p)

        # extras: permissions whose codename is not add_/change_/delete_/view_ (custom model permissions, etc.)
        rows.append(
            {
                'label': label,
                'add': buckets['add'],
                'change': buckets['change'],
                'delete': buckets['delete'],
                'view': buckets['view'],
                'extras': extras,
            }
        )
    return rows
