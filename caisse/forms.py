from django import forms

from stock.models import Product

from .models import BankAccount, Deposit, Expense, ExpenseCategory, PharmacySale


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
        self.fields["product"].queryset = Product.objects.filter(active=True)
        self.fields["product"].required = False
        self.fields["product"].empty_label = "— Montant global (sans produit) —"

    def clean(self):
        data = super().clean()
        if not data.get("product") and not data.get("description"):
            data["description"] = "Ventes pharmacie"
        if data.get("product") and not data.get("unit_price"):
            data["unit_price"] = data["product"].sale_price
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
