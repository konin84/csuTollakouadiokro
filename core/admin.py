from django.contrib import admin

from .models import AuditLog, Facility


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ("name", "opening_date", "opening_cash", "cash_tolerance")

    def has_add_permission(self, request):
        return not Facility.objects.exists()


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "action", "model", "object_repr")
    list_filter = ("action", "model")
    search_fields = ("object_repr",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
