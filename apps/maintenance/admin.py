from django.contrib import admin

from .models import MaintenanceComment, MaintenanceRequest, Vendor


class CommentInline(admin.TabularInline):
    model = MaintenanceComment
    extra = 0


@admin.register(MaintenanceRequest)
class MaintenanceRequestAdmin(admin.ModelAdmin):
    list_display = ("ticket", "unit", "title", "priority", "status", "assigned_to")
    list_filter = ("status", "priority")
    inlines = [CommentInline]


admin.site.register(Vendor)
