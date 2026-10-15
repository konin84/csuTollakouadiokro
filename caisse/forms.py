from django import forms
from django.db.models import Sum

from core.models import Facility
from stock.models import Product

from .models import BankAccount, Deposit, Expense, ExpenseCategory, PharmacySale, Visit


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["category", "fund", "amount", "description", "beneficiary", "receipt"]
        widgets = {
            "amount": forms.NumberInput(attrs={"min": 1, "step": 1, "inputmode": "numeric"}),
            "description": forms.TextInput(attrs={"placeholder": "Ex. achat de 3 paquets de rame"}),
            "beneficiary": forms.TextInput(attrs={"placeholder": "Facultatif"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = ExpenseCategory.objects.filter(active=True)
        self.fields["receipt"].widget.attrs["accept"] = "image/*,application/pdf"


class SaleForm(forms.ModelForm):
    class Meta:
        model = PharmacySale
        fields = ["product", "description", "quantity", "unit_price"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"min": 1, "step": 1, "inputmode": "numeric"}),
            "unit_price": forms.NumberInput(attrs={"min": 0, "step": 1, "inputmode": "numeric"}),
            "description": forms.TextInput(attrs={"placeholder": "Ex. ventes du jour (sans détail)"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["product"]
        field.queryset = Product.objects.filter(active=True).annotate(qty=Sum("movements__quantity"))
        field.label_from_instance = lambda p: f"{p.name} — stock : {p.qty or 0}"
        field.required = False
        field.empty_label = "— Montant global (sans produit) —"

    def clean(self):
        data = super().clean()
        product = data.get("product")
        if not product and not data.get("description"):
            data["description"] = "Ventes pharmacie"
        if product and not data.get("unit_price"):
            data["unit_price"] = product.sale_price
        if product and data.get("quantity") and Facility.current().block_negative_stock:
            available = product.qty or 0
            if data["quantity"] > available:
                self.add_error("quantity", f"Stock insuffisant pour « {product.name} » : {max(available, 0)} "
                                           "disponible(s). Si le stock réel est différent, faites un inventaire.")
        return data


class DepositForm(forms.ModelForm):
    class Meta:
        model = Deposit
        fields = ["date", "account", "amount", "reference", "depositor", "slip", "note"]
        widgets = {
            "date": DateInput(),
            "amount": forms.NumberInput(attrs={"min": 1, "step": 1, "inputmode": "numeric"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = BankAccount.objects.filter(active=True)
        self.fields["slip"].widget.attrs["accept"] = "image/*,application/pdf"


class CloseForm(forms.Form):
    counted_cash = forms.IntegerField(label="Argent compté dans la caisse (F)", min_value=0,
                                      widget=forms.NumberInput(attrs={"inputmode": "numeric", "step": 1}))
    notes = forms.CharField(label="Observations", required=False,
                            widget=forms.Textarea(attrs={"rows": 2}))


class ReopenForm(forms.Form):
    reason = forms.CharField(label="Motif de la réouverture", max_length=255)


class VisitForm(forms.ModelForm):
    class Meta:
        model = Visit
        fields = ["patient_name", "phone", "sex", "age"]
        widgets = {
            "patient_name": forms.TextInput(attrs={"autofocus": True, "autocomplete": "off",
                                                   "placeholder": "Ex. KOUASSI Amenan Marie"}),
            "phone": forms.TextInput(attrs={"inputmode": "tel", "placeholder": "Facultatif"}),
            "age": forms.NumberInput(attrs={"min": 0, "max": 130, "inputmode": "numeric"}),
        }

    def clean_patient_name(self):
        name = " ".join(self.cleaned_data["patient_name"].split())
        if len(name) < 2:
            raise forms.ValidationError("Indiquez le nom du patient.")
        return name


class CancelVisitForm(forms.Form):
    reason = forms.CharField(label="Motif de l'annulation", max_length=255)
