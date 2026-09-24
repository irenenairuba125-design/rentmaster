from django.urls import path

from . import views

app_name = "inspections"
urlpatterns = [
    path("", views.inspection_list, name="list"),
    path("new/", views.inspection_create, name="create"),
    path("<int:pk>/", views.inspection_detail, name="detail"),
    path("items/<int:pk>/maintenance/", views.item_to_maintenance, name="item_to_maintenance"),
]
