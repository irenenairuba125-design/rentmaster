from django.contrib import admin

from .models import Lease, Tenant, TenantDocument


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("tenant_id", "full_name", "phone", "email", "user")
    search_fields = ("tenant_id", "full_name", "phone", "email", "national_id")


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = ("pk", "tenant", "unit", "start_date", "end_date", "monthly_rent", "status")
    list_filter = ("status", "payment_frequency")


admin.site.register(TenantDocument)
