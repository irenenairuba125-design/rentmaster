from django.contrib import admin

from .models import AuditLog, Notification, Sequence


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "model", "object_repr", "message")
    list_filter = ("action", "model")
    search_fields = ("object_repr", "message", "user__username")

    # The audit trail is append-only.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Notification)
admin.site.register(Sequence)
