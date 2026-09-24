from django.contrib import admin

from .models import Inspection, InspectionItem, InspectionPhoto


class ItemInline(admin.TabularInline):
    model = InspectionItem
    extra = 0


class PhotoInline(admin.TabularInline):
    model = InspectionPhoto
    extra = 0


@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = ("number", "unit", "kind", "inspection_date", "overall", "inspector")
    list_filter = ("kind", "overall")
    inlines = [ItemInline, PhotoInline]
