from django.urls import path

from . import views

app_name = "vacancies"
urlpatterns = [
    path("", views.public_listings, name="public_list"),
    path("<int:pk>/", views.public_listing, name="public_detail"),
    path("manage/", views.listing_list, name="listing_list"),
    path("manage/new/", views.listing_form, name="listing_create"),
    path("manage/<int:pk>/edit/", views.listing_form, name="listing_edit"),
    path("applications/", views.application_list, name="application_list"),
    path("applications/<int:pk>/", views.application_detail, name="application_detail"),
    path("applications/<int:pk>/approve/", views.application_approve, name="application_approve"),
]
