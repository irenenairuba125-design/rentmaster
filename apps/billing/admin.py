from django.contrib import admin

from .models import DepositTransaction, Invoice, InvoiceItem, Payment, Receipt, UtilityReading


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "lease", "period_start", "due_date", "total", "amount_paid", "status")
    list_filter = ("status",)
    search_fields = ("number", "lease__tenant__full_name")
    inlines = [InvoiceItemInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("pk", "invoice", "amount", "method", "status", "provider_reference", "created_at")
    list_filter = ("status", "method")
    # Status changes must go through the app so receipts, invoices and the audit trail stay consistent.
    readonly_fields = ("status", "verified_by", "verified_at", "provider_reference", "provider_response")


admin.site.register(Receipt)
admin.site.register(UtilityReading)
admin.site.register(DepositTransaction)
