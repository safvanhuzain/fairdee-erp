from django.urls import path

from . import views
from .document_form import DeskAutoDocumentCreateView, DeskAutoDocumentUpdateView
from .document_list import DeskAutoDocumentListView
from .document_tree import DeskAutoDocumentTreeView

app_name = 'desk'

urlpatterns = [
    path('', views.DeskHomeView.as_view(), name='home'),
    path('accounts/user/', views.DeskUserListView.as_view(), name='user_list'),
    path(
        'desk/dataimport/api/fields/',
        views.DeskDataImportTemplateFieldsView.as_view(),
        name='dataimport_template_fields',
    ),
    path(
        'desk/dataimport/template-download/',
        views.DeskDataImportTemplateDownloadView.as_view(),
        name='dataimport_template_download',
    ),
    path(
        '<slug:app_label>/<slug:model_name>/<int:pk>/change/',
        DeskAutoDocumentUpdateView.as_view(),
        name='document_change',
    ),
    path(
        '<slug:app_label>/<slug:model_name>/new/',
        DeskAutoDocumentCreateView.as_view(),
        name='document_create',
    ),
    path(
        '<slug:app_label>/<slug:model_name>/tree/',
        DeskAutoDocumentTreeView.as_view(),
        name='document_tree',
    ),
    path('<slug:app_label>/<slug:model_name>/', DeskAutoDocumentListView.as_view(), name='document_list'),
]
