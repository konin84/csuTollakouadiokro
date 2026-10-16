from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum

from core.audit import track


class Product(models.Model):
    FORMS = [
        ("COMPRIME", "Comprimé / gélule"),
        ("SIROP", "Sirop / suspension"),
        ("INJECTABLE", "Injectable"),
        ("SOLUTE", "Soluté / perfusion"),
        ("CONSOMMABLE", "Consommable médical"),
        ("POMMADE", "Pommade / crème"),
        ("AUTRE", "Autre"),
    ]
    code = models.CharField("code", max_length=40, blank=True)
    name = models.CharField("désignation", max_length=160, unique=True)
    form = models.CharField("forme", max_length=20, choices=FORMS, default="AUTRE")
    # Le stock est compté dans la plus petite unité vendue (ex. comprimé). Le produit peut être acheté par
    # boîte (purchase_*) et vendu aussi par plaquette (pack_*) : les quantités sont converties en unités de stock.
    unit = models.CharField("unité de stock", max_length=40, default="unité",
                            help_text="La plus petite unité vendue, dans laquelle le stock est compté. "
                                      "Ex. comprimé, flacon, sachet.")
    sale_price = models.PositiveIntegerField("prix de vente par unité de stock (F)", default=0)
    pack_unit = models.CharField("autre unité de vente", max_length=40, blank=True,
                                 help_text="Ex. plaquette. Vide si le produit n'est vendu qu'à l'unité de stock.")
    pack_size = models.PositiveIntegerField("unités de stock par unité de vente", null=True, blank=True,
                                            validators=[MinValueValidator(2)], help_text="Ex. 10 comprimés.")
    pack_price = models.PositiveIntegerField("prix de vente de cette unité (F)", default=0)
    purchase_unit = models.CharField("unité d'achat", max_length=40, blank=True,
                                     help_text="Ex. boîte, carton. Vide si acheté à l'unité de stock.")
    purchase_size = models.PositiveIntegerField("unités de stock par unité d'achat", default=1,
                                                validators=[MinValueValidator(1)], help_text="Ex. 100 comprimés.")
    purchase_price = models.PositiveIntegerField("dernier prix d'achat par unité d'achat (F)", default=0)
    reorder_level = models.PositiveIntegerField("seuil d'alerte", default=0,
                                                help_text="Alerte quand le stock descend à ce niveau.")
    active = models.BooleanField("actif", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "produit"
        verbose_name_plural = "produits"

    def __str__(self):
        return self.name

    def clean(self):
        if self.pack_unit and not self.pack_size:
            raise ValidationError({"pack_size": "Indiquez combien d'unités de stock contient cette unité de vente."})
        if self.pack_unit and not self.pack_price:
            raise ValidationError({"pack_price": "Indiquez le prix de vente de cette unité."})
        if not self.purchase_unit:
            self.purchase_size = 1

    @property
    def has_pack(self):
        return bool(self.pack_unit and self.pack_size)

    @property
    def buy_unit(self):
        return self.purchase_unit or self.unit

    @property
    def unit_cost(self) -> Decimal:
        """Coût d'achat d'une unité de stock (ex. prix de la boîte / 100 comprimés)."""
        return Decimal(self.purchase_price) / (self.purchase_size or 1)

    def stock_value(self, qty) -> int:
        return round(max(qty or 0, 0) * self.unit_cost)

    def sale_units(self):
        """Unités proposées à la vente : (code, libellé, unités de stock, prix)."""
        units = [("unite", self.unit, 1, self.sale_price)]
        if self.has_pack:
            units.append(("pack", self.pack_unit, self.pack_size, self.pack_price))
        return units

    def describe(self, qty):
        """Ex. 1 045 comprimés -> « 10 boîte(s) + 45 comprimé(s) »  (vide si achat à l'unité)."""
        if not self.purchase_unit or self.purchase_size <= 1 or not qty or qty < 0:
            return ""
        boxes, rest = divmod(qty, self.purchase_size)
        return f"{boxes} {self.purchase_unit}(s)" + (f" + {rest} {self.unit}(s)" if rest else "")

    @property
    def stock_qty(self):
        if hasattr(self, "qty"):
            return self.qty or 0
        return self.movements.aggregate(s=Sum("quantity"))["s"] or 0


class Supplier(models.Model):
    name = models.CharField("nom", max_length=160, unique=True)
    phone = models.CharField("téléphone", max_length=60, blank=True)
    address = models.CharField("adresse", max_length=200, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "fournisseur"
        verbose_name_plural = "fournisseurs"

    def __str__(self):
        return self.name


class PurchaseOrder(models.Model):
    DRAFT = "BROUILLON"
    ORDERED = "COMMANDEE"
    RECEIVED = "RECUE"
    CANCELLED = "ANNULEE"
    STATUSES = [(DRAFT, "Brouillon"), (ORDERED, "Commandée"), (RECEIVED, "Reçue"), (CANCELLED, "Annulée")]

    number = models.CharField("n° de commande", max_length=30, unique=True)
    date = models.DateField("date de commande")
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.PROTECT,
                                 verbose_name="fournisseur")
    status = models.CharField("statut", max_length=12, choices=STATUSES, default=DRAFT)
    received_date = models.DateField("date de réception", null=True, blank=True)
    note = models.CharField("remarque", max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "commande"
        verbose_name_plural = "commandes"

    def __str__(self):
        return f"Commande {self.number}"

    @property
    def total(self):
        return sum(line.total for line in self.lines.all())

    @classmethod
    def next_number(cls, day):
        prefix = f"BC-{day:%Y}-"
        last = cls.objects.filter(number__startswith=prefix).order_by("-number").first()
        n = int(last.number.rsplit("-", 1)[1]) + 1 if last else 1
        return f"{prefix}{n:03d}"


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="produit")
    # quantités et prix par unité d'achat (ex. boîte) ; units_per_pack : contenu en unités de stock à la commande
    quantity = models.PositiveIntegerField("quantité commandée")
    unit_cost = models.PositiveIntegerField("prix d'achat par unité d'achat (F)", default=0)
    units_per_pack = models.PositiveIntegerField("unités de stock par unité d'achat", default=1)
    received_quantity = models.PositiveIntegerField("quantité reçue", null=True, blank=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "ligne de commande"
        verbose_name_plural = "lignes de commande"

    def __str__(self):
        return f"{self.product} × {self.quantity}"

    @property
    def total(self):
        return self.quantity * self.unit_cost

    @property
    def unit_label(self):
        """Unité de la quantité commandée (ex. boîte), ou l'unité de stock pour un produit acheté à l'unité."""
        return (self.product.purchase_unit or self.product.unit) if self.units_per_pack > 1 else self.product.unit


class StockMovement(models.Model):
    INITIAL = "INITIAL"
    RECEPTION = "RECEPTION"
    ENTRY = "ENTREE"
    SALE = "VENTE"
    ADJUST = "INVENTAIRE"
    LOSS = "PERTE"
    KINDS = [
        (INITIAL, "Stock initial"),
        (RECEPTION, "Réception commande"),
        (ENTRY, "Entrée directe (achat, don)"),
        (SALE, "Vente"),
        (ADJUST, "Ajustement d'inventaire"),
        (LOSS, "Perte / périmé / casse"),
    ]

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements",
                                verbose_name="produit")
    date = models.DateField("date")
    kind = models.CharField("type", max_length=12, choices=KINDS)
    quantity = models.IntegerField("quantité (+ entrée / − sortie)")
    unit_cost = models.PositiveIntegerField("coût unitaire (F)", default=0)
    reference = models.CharField("référence", max_length=120, blank=True)
    note = models.CharField("remarque", max_length=255, blank=True)
    sale = models.OneToOneField("caisse.PharmacySale", null=True, blank=True, on_delete=models.CASCADE,
                                related_name="movement")
    order_line = models.ForeignKey(PurchaseOrderLine, null=True, blank=True, on_delete=models.CASCADE,
                                   related_name="movements")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "mouvement de stock"
        verbose_name_plural = "mouvements de stock"

    def __str__(self):
        return f"{self.date:%d/%m/%Y} {self.get_kind_display()} {self.product} {self.quantity:+d}"


for _model in (Product, Supplier, PurchaseOrder, PurchaseOrderLine, StockMovement):
    track(_model)
