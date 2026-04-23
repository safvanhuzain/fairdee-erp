from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path
from django.views.generic import RedirectView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.desk.views import DeskLoginView

admin.site.site_header = 'Fairdee Finance'
admin.site.site_title = 'Fairdee Finance'


@api_view(['GET'])
@permission_classes([AllowAny])
def health(_request):
    return Response({'status': 'ok', 'service': 'fairdee-finance', 'version': '1'})


urlpatterns = [
    path('', RedirectView.as_view(url='/app/', permanent=False)),
    path('admin/', admin.site.urls),
    path('login/', DeskLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(next_page='/login/'), name='logout'),
    path('app/', include('apps.desk.urls')),
    path('api/v1/health/', health, name='health'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
