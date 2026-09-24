from django.urls import path

from . import views

app_name = "tenants"
urlpatterns = [
    path("", views.tenant_list, name="list"),
    path("new/", views.tenant_form, name="create"),
    path("<int:pk>/", views.tenant_detail, name="detail"),
    path("<int:pk>/edit/", views.tenant_form, name="edit"),
    path("<int:pk>/documents/", views.tenant_document_upload, name="document_upload"),
    path("<int:pk>/create-login/", views.tenant_create_login, name="create_login"),
    path("leases/", views.lease_list, name="lease_list"),
    path("leases/new/", views.lease_form, name="lease_create"),
    path("leases/<int:pk>/", views.lease_detail, name="lease_detail"),
    path("leases/<int:pk>/edit/", views.lease_form, name="lease_edit"),
    path("leases/<int:pk>/terminate/", views.lease_terminate, name="lease_terminate"),
    path("leases/<int:pk>/deposit/", views.lease_deposit_add, name="lease_deposit_add"),
]
