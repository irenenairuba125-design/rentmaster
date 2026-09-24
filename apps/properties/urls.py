from django.urls import path

from . import views

app_name = "properties"
urlpatterns = [
    path("", views.property_list, name="list"),
    path("new/", views.property_form, name="create"),
    path("<int:pk>/", views.property_detail, name="detail"),
    path("<int:pk>/edit/", views.property_form, name="edit"),
    path("<int:property_pk>/buildings/new/", views.building_form, name="building_create"),
    path("buildings/<int:building_pk>/units/new/", views.unit_form, name="unit_create"),
    path("units/<int:pk>/", views.unit_detail, name="unit_detail"),
    path("units/<int:pk>/edit/", views.unit_form, name="unit_edit"),
]
