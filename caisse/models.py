from datetime import date as date_cls

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.audit import track
from core.models import Facility

# Les deux caisses du centre, chacune versée sur sa propre banque.
FUND_ENTREE = "ENTREE"
FUND_PHARMA = "PHARMA"
FUNDS = [
    (FUND_ENTREE, "Entrées + Laboratoire"),
    (FUND_PHARMA, "Pharmacie + Échographie"),
]
FUND_LABELS = dict(FUNDS)


class Act(models.Model):
    """Acte ou prestation facturée (consultation, CPN, accouchement…)."""

    CATEGORIES = [
        ("CONSULT", "Consultations"),
        ("MATERNITE", "Maternité"),
        ("SOINS", "Soins"),
        ("LABO", "Laboratoire"),
        ("IMAGERIE", "Imagerie"),
        ("DOCUMENTS", "Carnets et documents"),
        ("TRANSPORT", "Transport"),
        ("AUTRE", "Autre"),
    ]
    MODE_QUANTITY = "QTE"
    MODE_AMOUNT = "MONTANT"
    MODES = [
        (MODE_QUANTITY, "Nombre d'actes × prix unitaire"),
        (MODE_AMOUNT, "Montant global saisi (ex. laboratoire)"),
    ]

    code = models.SlugField("code", max_length=40, unique=True)
    name = models.CharField("libellé", max_length=120)
    category = models.CharField("catégorie", max_length=20, choices=CATEGORIES, default="AUTRE")
    fund = models.CharField("caisse", max_length=10, choices=FUNDS, default=FUND_ENTREE)
    entry_mode = models.CharField("mode de saisie", max_length=10, choices=MODES, default=MODE_QUANTITY)
    is_lab = models.BooleanField(
        "recette de laboratoire", default=False,
        help_text="Les commissions laboratoire (prescripteurs, partenaire, ONG…) s'appliquent à cet acte.",
    )
    order = models.PositiveIntegerField("ordre d'affichage", default=100)
    active = models.BooleanField("actif", default=True)
    product = models.ForeignKey(
        "stock.Product", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        verbose_name="produit consommé",
        help_text="Produit retiré du stock à chaque acte (ex. Gant → 1 paire de gants). Laisser vide sinon.",
    )
    product_quantity = models.PositiveIntegerField("quantité consommée par acte", default=1)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "acte / prestation"
        verbose_name_plural = "actes et prestations"

    def __str__(self):
        return self.name

    @property
    def by_quantity(self):
        return self.entry_mode == self.MODE_QUANTITY

    def price_on(self, day):
        price = self.prices.filter(valid_from__lte=day).order_by("-valid_from").first()
        return price.price if price else None


class ActPrice(models.Model):
    act = models.ForeignKey(Act, on_delete=models.CASCADE, related_name="prices", verbose_name="acte")
    price = models.PositiveIntegerField("prix unitaire (F)")
    valid_from = models.DateField("applicable à partir du")

    class Meta:
        ordering = ["act", "-valid_from"]
        unique_together = [("act", "valid_from")]
        verbose_name = "tarif"
        verbose_name_plural = "tarifs"

    def __str__(self):
        return f"{self.act} : {self.price} F dès le {self.valid_from:%d/%m/%Y}"


class CommissionRule(models.Model):
    """Répartition de la recette laboratoire.

    Ex. 15 % prescripteurs (payé), 60 % laboratoire partenaire (payé),
    25 % ONG AIP (conservé dans la caisse Entrées + Labo et versé à la banque).
    """

    name = models.CharField("libellé", max_length=120)
    beneficiary = models.CharField("bénéficiaire", max_length=120, blank=True)
    rate = models.DecimalField("taux (%)", max_digits=5, decimal_places=2)
    retained = models.BooleanField(
        "conservé en caisse", default=False,
        help_text="Coché : cette part reste dans la caisse (versée à la banque). "
                  "Décoché : elle est reversée au bénéficiaire et sort de la caisse.",
    )
    valid_from = models.DateField("applicable à partir du")
    valid_to = models.DateField("jusqu'au (inclus)", null=True, blank=True)
    order = models.PositiveIntegerField("ordre", default=10)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "règle de commission laboratoire"
        verbose_name_plural = "règles de commission laboratoire"

    def __str__(self):
        return f"{self.name} ({self.rate} %)"

    @classmethod
    def active_on(cls, day):
        return cls.objects.filter(valid_from__lte=day).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=day))


class ExpenseCategory(models.Model):
    name = models.CharField("libellé", max_length=120, unique=True)
    default_fund = models.CharField("payée par défaut sur la caisse", max_length=10, choices=FUNDS,
                                    default=FUND_ENTREE)
    order = models.PositiveIntegerField("ordre", default=100)
    active = models.BooleanField("active", default=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "catégorie de dépense"
        verbose_name_plural = "catégories de dépense"

    def __str__(self):
        return self.name


class BankAccount(models.Model):
    name = models.CharField("libellé", max_length=120)
    bank = models.CharField("banque", max_length=120)
    number = models.CharField("n° de compte", max_length=60, blank=True)
    fund = models.CharField("caisse versée sur ce compte", max_length=10, choices=FUNDS, blank=True,
                            help_text="Laisser vide si ce compte reçoit l'argent des deux caisses.")
    active = models.BooleanField("actif", default=True)

    class Meta:
        ordering = ["fund", "name"]
        verbose_name = "compte bancaire"
        verbose_name_plural = "comptes bancaires"

    def __str__(self):
        return f"{self.bank} – {self.name}" if self.name != self.bank else self.bank


class CashSession(models.Model):
    """Une journée de caisse."""

    OPEN = "OUVERTE"
    CLOSED = "CLOTUREE"
    VALIDATED = "VALIDEE"
    STATUSES = [(OPEN, "Ouverte"), (CLOSED, "Clôturée"), (VALIDATED, "Validée")]

    facility = models.ForeignKey(Facility, on_delete=models.PROTECT, verbose_name="établissement")
    date = models.DateField("date")
    status = models.CharField("statut", max_length=10, choices=STATUSES, default=OPEN)
    notes = models.TextField("observations", blank=True)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="+", verbose_name="ouverte par")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    counted_cash = models.IntegerField("argent compté à la clôture", null=True, blank=True)
    expected_cash = models.IntegerField("solde théorique à la clôture", null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="+", verbose_name="clôturée par")
    closed_at = models.DateTimeField("clôturée le", null=True, blank=True)
    validated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+", verbose_name="validée par")
    validated_at = models.DateTimeField("validée le", null=True, blank=True)
    imported = models.BooleanField("importée depuis Excel", default=False)

    class Meta:
        ordering = ["-date"]
        unique_together = [("facility", "date")]
        verbose_name = "journée de caisse"
        verbose_name_plural = "journées de caisse"

    def __str__(self):
        return f"Journée du {self.date:%d/%m/%Y}"

    @property
    def is_open(self):
        return self.status == self.OPEN

    @property
    def cash_gap(self):
        if self.counted_cash is None or self.expected_cash is None:
            return None
        return self.counted_cash - self.expected_cash

    @property
    def is_future(self):
        return self.date > date_cls.today()


class ActEntry(models.Model):
    session = models.ForeignKey(CashSession, on_delete=models.CASCADE, related_name="entries")
    act = models.ForeignKey(Act, on_delete=models.PROTECT, verbose_name="acte")
    quantity = models.PositiveIntegerField("nombre", default=0)
    unit_price = models.PositiveIntegerField("prix unitaire", null=True, blank=True)
    amount = models.IntegerField("montant", default=0)
    manual_amount = models.BooleanField(
        "montant saisi manuellement", default=False,
        help_text="Montant ne correspondant pas à nombre × prix (ex. données importées d'Excel).",
    )
    note = models.CharField("remarque", max_length=255, blank=True)

    class Meta:
        unique_together = [("session", "act")]
        ordering = ["act__order"]
        verbose_name = "recette par acte"
        verbose_name_plural = "recettes par acte"

    def __str__(self):
        return f"{self.act} × {self.quantity}"

    def save(self, *args, **kwargs):
        if self.act.by_quantity and not self.manual_amount:
            if self.unit_price is None:
                self.unit_price = self.act.price_on(self.session.date) or 0
            self.amount = self.quantity * self.unit_price
        super().save(*args, **kwargs)


class Expense(models.Model):
    session = models.ForeignKey(CashSession, on_delete=models.CASCADE, related_name="expenses")
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, verbose_name="catégorie")
    fund = models.CharField("payée sur la caisse", max_length=10, choices=FUNDS)
    amount = models.PositiveIntegerField("montant (F)")
    description = models.CharField("motif", max_length=255)
    beneficiary = models.CharField("bénéficiaire", max_length=120, blank=True)
    receipt = models.FileField("justificatif", upload_to="depenses/%Y/%m/", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "dépense"
        verbose_name_plural = "dépenses"

    def __str__(self):
        return f"{self.session.date:%d/%m/%Y} – {self.description} ({self.amount} F)"


class Deposit(models.Model):
    facility = models.ForeignKey(Facility, on_delete=models.PROTECT, verbose_name="établissement")
    date = models.DateField("date du versement")
    account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, verbose_name="compte")
    amount = models.PositiveIntegerField("montant (F)")
    reference = models.CharField("n° de bordereau", max_length=80, blank=True)
    depositor = models.CharField("déposant", max_length=120, blank=True)
    slip = models.FileField("bordereau scanné / photo", upload_to="versements/%Y/%m/", blank=True)
    note = models.CharField("remarque", max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "versement bancaire"
        verbose_name_plural = "versements bancaires"

    def __str__(self):
        return f"Versement {self.account} du {self.date:%d/%m/%Y} : {self.amount} F"



class Visit(models.Model):
    """Passage d'un patient à la caisse : un reçu numéroté avec ses actes et ses produits.

    Les actes s'ajoutent aux nombres saisis dans la grille de la journée ; les produits
    sont des ventes pharmacie (PharmacySale.visit) et sortent du stock.
    Un reçu n'est jamais supprimé : il est annulé, avec un motif."""

    SEXES = [("F", "Féminin"), ("M", "Masculin")]

    session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="visits")
    number = models.CharField("n° de reçu", max_length=20, unique=True)
    patient_name = models.CharField("nom et prénoms du patient", max_length=150)
    phone = models.CharField("téléphone", max_length=30, blank=True)
    sex = models.CharField("sexe", max_length=1, choices=SEXES, blank=True)
    age = models.PositiveSmallIntegerField("âge (ans)", null=True, blank=True,
                                           help_text="0 pour un enfant de moins d'un an.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", verbose_name="caissier")
    created_at = models.DateTimeField("heure", auto_now_add=True)
    cancelled = models.BooleanField("annulé", default=False)
    cancel_reason = models.CharField("motif d'annulation", max_length=255, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+", verbose_name="annulé par")
    cancelled_at = models.DateTimeField("annulé le", null=True, blank=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "passage patient"
        verbose_name_plural = "passages patients"

    def __str__(self):
        return f"Reçu {self.number} – {self.patient_name}"

    @property
    def total(self):
        return sum(a.amount for a in self.acts.all()) + sum(s.amount for s in self.sales.all())

    @classmethod
    def next_number(cls, day):
        prefix = f"{day:%Y}-"
        last = cls.objects.filter(number__startswith=prefix).order_by("-number").first()
        n = int(last.number.rsplit("-", 1)[1]) + 1 if last else 1
        return f"{prefix}{n:06d}"


class VisitAct(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="acts")
    act = models.ForeignKey(Act, on_delete=models.PROTECT, verbose_name="acte")
    quantity = models.PositiveIntegerField("nombre", default=1)
    unit_price = models.PositiveIntegerField("prix unitaire", null=True, blank=True)
    amount = models.PositiveIntegerField("montant (F)", default=0)

    class Meta:
        ordering = ["id"]
        verbose_name = "acte du passage"
        verbose_name_plural = "actes du passage"

    def __str__(self):
        return f"{self.act} × {self.quantity}"


class PharmacySale(models.Model):
    """Vente pharmacie du jour. Avec un produit : le stock est décrémenté.
    Sans produit : montant global (comme dans l'ancien tableau Excel).
    Avec un passage (visit) : produit vendu à un patient, sur son reçu."""

    session = models.ForeignKey(CashSession, on_delete=models.CASCADE, related_name="sales")
    visit = models.ForeignKey(Visit, null=True, blank=True, on_delete=models.CASCADE, related_name="sales",
                              verbose_name="passage")
    product = models.ForeignKey("stock.Product", null=True, blank=True, on_delete=models.PROTECT,
                                verbose_name="produit")
    description = models.CharField("libellé", max_length=200, blank=True)
    quantity = models.PositiveIntegerField("quantité", default=1)
    unit_price = models.PositiveIntegerField("prix unitaire (F)", default=0)
    amount = models.PositiveIntegerField("montant (F)", default=0)

    class Meta:
        ordering = ["id"]
        verbose_name = "vente pharmacie"
        verbose_name_plural = "ventes pharmacie"

    def __str__(self):
        label = self.product.name if self.product_id else (self.description or "Ventes pharmacie")
        return f"{label} × {self.quantity}"

    def save(self, *args, **kwargs):
        self.amount = self.quantity * self.unit_price
        super().save(*args, **kwargs)


for _model in (Act, ActPrice, CommissionRule, ExpenseCategory, BankAccount, CashSession, ActEntry, Expense,
               Deposit, Visit, VisitAct, PharmacySale):
    track(_model)
