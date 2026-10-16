from django.contrib import admin

from .models import (Act, ActEntry, ActPrice, BankAccount, CashSession, CommissionRule, Deposit, Expense,
                     ExpenseCategory, PharmacySale)

admin.site.site_header = "CSU Caisse – Paramètres"
admin.site.site_title = "CSU Caisse"
admin.site.index_title = "Paramètres de l'application"


class ActPriceInline(admin.TabularInline):
    model = ActPrice
    extra = 1


@admin.register(Act)
class ActAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "fund", "entry_mode", "is_lab", "current_price", "order", "active")
    list_editable = ("order", "active")
    list_filter = ("category", "fund", "active")
    search_fields = ("name", "code")
    prepopulated_fields = {"code": ("name",)}
    inlines = [ActPriceInline]

    @admin.display(description="tarif actuel")
    def current_price(self, obj):
        from datetime import date

        p = obj.price_on(date.today())
        return f"{p:,} F".replace(",", " ") if p is not None else "—"


@admin.register(CommissionRule)
class CommissionRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "beneficiary", "rate", "retained", "valid_from", "valid_to", "order")


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "default_fund", "order", "active")
    list_editable = ("order", "active")


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("bank", "name", "number", "fund", "active")


class ActEntryInline(admin.TabularInline):
    model = ActEntry
    extra = 0


class ExpenseInline(admin.TabularInline):
    model = Expense
    extra = 0


class SaleInline(admin.TabularInline):
    model = PharmacySale
    extra = 0
    autocomplete_fields = ("product",)


@admin.register(CashSession)
class CashSessionAdmin(admin.ModelAdmin):
    list_display = ("date", "status", "counted_cash", "expected_cash", "closed_by", "validated_by", "imported")
    list_filter = ("status", "imported")
    date_hierarchy = "date"
    inlines = [ActEntryInline, ExpenseInline, SaleInline]


@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ("date", "account", "amount", "reference", "depositor")
    list_filter = ("account",)
    date_hierarchy = "date"
