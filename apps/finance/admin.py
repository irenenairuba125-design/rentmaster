from django.contrib import admin

from .models import Expense


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("date", "property", "category", "description", "amount")
    list_filter = ("category", "property")
