from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ApiToken, User


@admin.register(User)
class RentmasterUserAdmin(UserAdmin):
    list_display = ("username", "get_full_name", "email", "role", "is_active")
    list_filter = ("role", "is_active")
    fieldsets = UserAdmin.fieldsets + (("RENTMASTER", {"fields": ("role", "phone")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("RENTMASTER", {"fields": ("role", "phone", "email", "first_name", "last_name")}),)


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    """Revoke a lost phone's access by deleting its token."""
    list_display = ("user", "device", "created_at", "last_used_at", "expires_at")
    readonly_fields = ("user", "key_hash", "device", "created_at", "last_used_at", "expires_at")

    def has_add_permission(self, request):
        return False
