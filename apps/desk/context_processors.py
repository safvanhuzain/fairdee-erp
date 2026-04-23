def desk_navigation(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {
            'desk_nav_sections': [],
            'desk_documents_catalog': [],
        }
    from apps.desk.registry import get_desk_documents_catalog, get_desk_nav_sections

    return {
        'desk_nav_sections': get_desk_nav_sections(request.user),
        'desk_documents_catalog': get_desk_documents_catalog(request.user),
    }
