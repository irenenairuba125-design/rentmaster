from django.contrib import admin

from .models import Building, Property, PropertyDocument, Unit


class BuildingInline(admin.TabularInline):
    model = Building
    extra = 0


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "property_type", "location", "owner", "status")
    list_filter = ("property_type", "status")
    search_fields = ("name", "code", "location")
    filter_horizontal = ("managers",)
    inlines = [BuildingInline]


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("number", "building", "unit_type", "monthly_rent", "status")
    list_filter = ("status", "unit_type", "building__property")
    search_fields = ("number",)


admin.site.register(Building)
admin.site.register(PropertyDocument)
