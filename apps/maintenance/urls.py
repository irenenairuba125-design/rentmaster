from django.urls import path

from . import views

app_name = "maintenance"
urlpatterns = [
    path("", views.request_list, name="list"),
    path("new/", views.request_create, name="create"),
    path("<int:pk>/", views.request_detail, name="detail"),
    path("<int:pk>/comment/", views.request_comment, name="comment"),
]
