from django import forms

from caisse.forms import DateInput

from .models import Product, PurchaseOrder, PurchaseOrderLine, StockMovement


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "code", "form", "unit", "sale_price", "purchase_price", "reorder_level", "active"]


class OrderForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ["date", "supplier", "note"]
        widgets = {"date": DateInput()}


class OrderLineForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrderLine
        fields = ["product", "quantity", "unit_cost"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"min": 1, "step": 1}),
            "unit_cost": forms.NumberInput(attrs={"min": 0, "step": 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(active=True)


class LossForm(forms.Form):
    product = forms.ModelChoiceField(label="Produit", queryset=Product.objects.filter(active=True))
    quantity = forms.IntegerField(label="Quantité sortie", min_value=1)
    date = forms.DateField(label="Date", widget=DateInput())
    note = forms.CharField(label="Motif", max_length=255,
                           widget=forms.TextInput(attrs={"placeholder": "Ex. périmé le 30/09, flacon cassé"}))


class InitialStockForm(forms.Form):
    date = forms.DateField(label="Date de l'inventaire", widget=DateInput())
    note = forms.CharField(label="Remarque", max_length=255, required=False)


MOVEMENT_KINDS_MANUAL = [k for k in StockMovement.KINDS if k[0] in (StockMovement.LOSS,)]
