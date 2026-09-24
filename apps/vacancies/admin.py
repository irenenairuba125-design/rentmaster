from django.contrib import admin

from .models import Application, Listing


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("title", "unit", "monthly_rent", "available_from", "is_published")
    list_filter = ("is_published",)


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("reference", "full_name", "phone", "listing", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("reference", "full_name", "phone")
