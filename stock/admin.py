from django.contrib import admin

from .models import Product, PurchaseOrder, PurchaseOrderLine, StockMovement, Supplier


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "form", "unit", "sale_price", "purchase_price", "reorder_level", "active")
    list_filter = ("form", "active")
    search_fields = ("name", "code")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "phone")
    search_fields = ("name",)


class LineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("number", "date", "supplier", "status")
    inlines = [LineInline]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("date", "product", "kind", "quantity", "reference")
    list_filter = ("kind",)
    search_fields = ("product__name",)
