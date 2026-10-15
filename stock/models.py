from django.conf import settings
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
    unit = models.CharField("unité de vente", max_length=40, default="unité",
                            help_text="Ex. comprimé, flacon, boîte, paquet.")
    sale_price = models.PositiveIntegerField("prix de vente (F)", default=0)
    purchase_price = models.PositiveIntegerField("dernier prix d'achat (F)", default=0)
    reorder_level = models.PositiveIntegerField("seuil d'alerte", default=0,
                                                help_text="Alerte quand le stock descend à ce niveau.")
    active = models.BooleanField("actif", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "produit"
        verbose_name_plural = "produits"

    def __str__(self):
        return self.name

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
    quantity = models.PositiveIntegerField("quantité commandée")
    unit_cost = models.PositiveIntegerField("prix unitaire d'achat (F)", default=0)
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


class StockMovement(models.Model):
    INITIAL = "INITIAL"
    RECEPTION = "RECEPTION"
    SALE = "VENTE"
    ADJUST = "INVENTAIRE"
    LOSS = "PERTE"
    KINDS = [
        (INITIAL, "Stock initial"),
        (RECEPTION, "Réception commande"),
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
