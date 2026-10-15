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
        self.fields["unit_cost"].required = False  # vide = dernier prix d'achat (voir order_detail)


class NewProductForm(ProductForm):
    initial_stock = forms.IntegerField(label="Stock initial", min_value=0, required=False,
                                       help_text="Quantité présente aujourd'hui (facultatif).")


class StockEntryForm(forms.Form):
    quantity = forms.IntegerField(label="Quantité ajoutée", min_value=1,
                                  widget=forms.NumberInput(attrs={"inputmode": "numeric", "step": 1}))
    date = forms.DateField(label="Date", widget=DateInput())
    unit_cost = forms.IntegerField(label="Prix d'achat unitaire (F)", min_value=0, required=False,
                                   help_text="Vide = dernier prix d'achat ; 0 pour un don.")
    reference = forms.CharField(label="Référence", max_length=120, required=False,
                                widget=forms.TextInput(attrs={"placeholder": "N° de facture, fournisseur, donateur…"}))
    note = forms.CharField(label="Remarque", max_length=255, required=False)


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
