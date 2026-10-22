from django import forms

from caisse.forms import DateInput
from core.forms import TrimTextMixin

from .models import Product, PurchaseOrder, PurchaseOrderLine, StockMovement


class ProductForm(TrimTextMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "code", "form", "unit", "sale_price", "pack_unit", "pack_size", "pack_price",
                  "supplier", "purchase_unit", "purchase_size", "purchase_price", "reorder_level", "active"]

    # libellés courts et exemples : les sections du formulaire (stock/_product_fields.html) expliquent le reste
    LABELS = {
        "name": ("Nom du produit", "Ex. PARACETAMOL 500 mg"),
        "code": ("Code (facultatif)", ""),
        "unit": ("Unité", "comprimé, flacon, sachet…"),
        "sale_price": ("Prix de vente d'une unité (F)", ""),
        "pack_unit": ("Conditionnement", "plaquette, boîte…"),
        "pack_size": ("Contient (unités)", "10"),
        "pack_price": ("Prix de vente (F)", ""),
        "supplier": ("Fournisseur", ""),
        "purchase_unit": ("Conditionnement d'achat", ""),
        "purchase_size": ("Contient (unités)", "100"),
        "purchase_price": ("Prix d'achat (F)", ""),
        "reorder_level": ("Seuil d'alerte (en unités)", ""),
    }

    # listes de choix (orthographe identique partout : reçus, rapports, inventaire)
    UNITS = ["comprimé", "gélule", "plaquette", "boîte", "flacon", "ampoule", "sachet", "tube", "suppositoire",
             "poche", "seringue", "paire", "unité"]
    PACKS = ["plaquette", "boîte", "sachet", "flacon", "paquet", "carton"]
    PURCHASE_PACKS = ["boîte", "carton", "paquet", "sachet", "flacon"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, (label, placeholder) in self.LABELS.items():
            field = self.fields[name]
            field.label, field.help_text = label, ""
            if placeholder:
                field.widget.attrs["placeholder"] = placeholder
        self.fields["reorder_level"].help_text = "« À commander » à ce niveau."
        self._choice_field("unit", self.UNITS)
        self._choice_field("pack_unit", self.PACKS, empty="— Aucun —")
        self.fields["supplier"].empty_label = "— Aucun —"
        self._choice_field("purchase_unit", self.PURCHASE_PACKS, empty="— À l'unité —")
        # facultatifs : un produit acheté et vendu à l'unité ne les remplit pas
        self.fields["pack_price"].required = False
        self.fields["purchase_size"].required = False

    def _choice_field(self, name, values, empty=None):
        """Liste déroulante ; une valeur déjà enregistrée hors liste reste proposée (rien ne se perd)."""
        old = self.fields[name]
        current = getattr(self.instance, name, "") or ""
        values = values + ([current] if current and current not in values else [])
        choices = ([("", empty)] if empty else []) + [(v, v) for v in values]
        self.fields[name] = forms.ChoiceField(label=old.label, choices=choices, required=old.required)

    def clean_pack_price(self):
        return self.cleaned_data.get("pack_price") or 0

    def clean_purchase_size(self):
        return self.cleaned_data.get("purchase_size") or 1

    def clean(self):
        data = super().clean()
        # un même mot pour deux contenances (ex. « boîte » de 10 à la vente et de 100 à l'achat) : source d'erreurs
        pack, buy = data.get("pack_unit"), data.get("purchase_unit")
        pack_size, buy_size = data.get("pack_size") or 0, data.get("purchase_size") or 1
        if pack and buy and pack == buy and pack_size and buy_size != pack_size:
            unit = data.get("unit") or "unité"
            self.add_error("purchase_unit", forms.ValidationError(
                f"« {buy} » contient déjà {pack_size} {unit}(s) à la vente (section 3) : ici il en contient {buy_size}. "
                f"Choisissez un autre conditionnement d'achat (ex. carton) ou mettez le même contenu."))
        return data


class OrderForm(TrimTextMixin, forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ["date", "supplier", "note"]
        widgets = {"date": DateInput()}


class OrderLineForm(TrimTextMixin, forms.ModelForm):
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
    initial_stock = forms.IntegerField(label="Total en stock", min_value=0, required=False)


class StockEntryForm(TrimTextMixin, forms.Form):
    """Quantité et prix par unité d'achat du produit (ex. boîte) : convertis en unités de stock à l'enregistrement."""
    quantity = forms.IntegerField(label="Quantité ajoutée", min_value=1,
                                  widget=forms.NumberInput(attrs={"inputmode": "numeric", "step": 1}))
    date = forms.DateField(label="Date", widget=DateInput())
    unit_cost = forms.IntegerField(label="Prix d'achat unitaire (F)", min_value=0, required=False,
                                   help_text="Vide = dernier prix d'achat ; 0 pour un don.")

    def __init__(self, *args, product=None, **kwargs):
        super().__init__(*args, **kwargs)
        if product is not None and product.purchase_unit:
            self.fields["quantity"].label = f"Nombre de {product.purchase_unit}s ({product.purchase_size} {product.unit}s)"
            self.fields["unit_cost"].label = f"Prix d'achat par {product.purchase_unit} (F)"
    reference = forms.CharField(label="Référence", max_length=120, required=False,
                                widget=forms.TextInput(attrs={"placeholder": "N° de facture, fournisseur, donateur…"}))
    note = forms.CharField(label="Remarque", max_length=255, required=False)


class LossForm(TrimTextMixin, forms.Form):
    product = forms.ModelChoiceField(label="Produit", queryset=Product.objects.filter(active=True))
    quantity = forms.IntegerField(label="Quantité sortie (en unités de stock, ex. comprimés)", min_value=1)
    date = forms.DateField(label="Date", widget=DateInput())
    note = forms.CharField(label="Motif", max_length=255,
                           widget=forms.TextInput(attrs={"placeholder": "Ex. périmé le 30/09, flacon cassé"}))


class InitialStockForm(TrimTextMixin, forms.Form):
    date = forms.DateField(label="Date de l'inventaire", widget=DateInput())
    note = forms.CharField(label="Remarque", max_length=255, required=False)


MOVEMENT_KINDS_MANUAL = [k for k in StockMovement.KINDS if k[0] in (StockMovement.LOSS,)]
