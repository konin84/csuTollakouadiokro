"""Calculs de caisse.

Règle retenue (colonne AJ de l'ancien tableau Excel) :

  Caisse Entrées + Labo  = actes de la caisse Entrées (y compris laboratoire)
                         − commissions laboratoire reversées (prescripteurs, partenaire)
                         − dépenses payées sur cette caisse
  Caisse Pharmacie + Écho = actes de la caisse Pharmacie (échographie)
                         + ventes pharmacie
                         − dépenses payées sur cette caisse (ristournes écho, divers pharmacie…)
  Recette nette du jour  = somme des deux caisses.

La part laboratoire « conservée » (ONG AIP, 25 %) reste dans la caisse Entrées + Labo.
"""
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Prefetch, Sum

from core.models import Facility

from .models import (FUND_ENTREE, FUND_PHARMA, FUNDS, Act, ActEntry, CashSession, CommissionRule, Deposit,
                     Expense, PharmacySale, Visit, VisitAct)


def round_fcfa(value) -> int:
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class Totals:
    """Totaux d'une journée ou d'une période."""

    acts_amount: dict = field(default_factory=lambda: defaultdict(int))  # act_id -> montant
    acts_qty: dict = field(default_factory=lambda: defaultdict(int))  # act_id -> nombre
    revenue_by_fund: dict = field(default_factory=lambda: defaultdict(int))  # actes uniquement
    lab: int = 0
    pharmacy: int = 0
    commissions: dict = field(default_factory=lambda: OrderedDict())  # nom -> {amount, retained}
    commissions_paid: int = 0
    commissions_retained: int = 0
    expenses_by_fund: dict = field(default_factory=lambda: defaultdict(int))
    expenses_by_category: dict = field(default_factory=lambda: defaultdict(int))
    sessions: int = 0
    patients: int = 0  # passages patients non annulés

    # --- dérivés ---
    @property
    def acts_total(self):
        return sum(self.revenue_by_fund.values())

    @property
    def gross(self):
        """Recette brute : tous les actes + pharmacie (colonnes U + V)."""
        return self.acts_total + self.pharmacy

    @property
    def entries_excl_lab(self):
        return self.revenue_by_fund[FUND_ENTREE] - self.lab

    @property
    def echo(self):
        return self.revenue_by_fund[FUND_PHARMA]

    @property
    def expenses_total(self):
        return sum(self.expenses_by_fund.values())

    @property
    def net_entree(self):
        return self.revenue_by_fund[FUND_ENTREE] - self.commissions_paid - self.expenses_by_fund[FUND_ENTREE]

    @property
    def net_pharma(self):
        return self.revenue_by_fund[FUND_PHARMA] + self.pharmacy - self.expenses_by_fund[FUND_PHARMA]

    @property
    def net_total(self):
        return self.net_entree + self.net_pharma

    def net_by_fund(self):
        return {FUND_ENTREE: self.net_entree, FUND_PHARMA: self.net_pharma}

    def add(self, other: "Totals"):
        for k, v in other.acts_amount.items():
            self.acts_amount[k] += v
        for k, v in other.acts_qty.items():
            self.acts_qty[k] += v
        for k, v in other.revenue_by_fund.items():
            self.revenue_by_fund[k] += v
        self.lab += other.lab
        self.pharmacy += other.pharmacy
        for name, c in other.commissions.items():
            cur = self.commissions.setdefault(name, {"amount": 0, "retained": c["retained"],
                                                     "beneficiary": c["beneficiary"]})
            cur["amount"] += c["amount"]
        self.commissions_paid += other.commissions_paid
        self.commissions_retained += other.commissions_retained
        for k, v in other.expenses_by_fund.items():
            self.expenses_by_fund[k] += v
        for k, v in other.expenses_by_category.items():
            self.expenses_by_category[k] += v
        self.sessions += other.sessions
        self.patients += other.patients
        return self


_rules_cache = {}


def _rules_on(day):
    key = day
    if key not in _rules_cache:
        _rules_cache[key] = list(CommissionRule.active_on(day))
    return _rules_cache[key]


def clear_caches():
    _rules_cache.clear()


def session_totals(session: CashSession) -> Totals:
    """Totaux d'une journée. Utilise les données préchargées si disponibles."""
    t = Totals(sessions=1)
    for e in session.entries.all():
        t.acts_amount[e.act_id] += e.amount
        t.acts_qty[e.act_id] += e.quantity
        t.revenue_by_fund[e.act.fund] += e.amount
        if e.act.is_lab:
            t.lab += e.amount
    # actes des passages patients, en plus des nombres saisis dans la grille
    for v in session.visits.all():
        if v.cancelled:
            continue
        t.patients += 1
        for line in v.acts.all():
            t.acts_amount[line.act_id] += line.amount
            t.acts_qty[line.act_id] += line.quantity
            t.revenue_by_fund[line.act.fund] += line.amount
            if line.act.is_lab:
                t.lab += line.amount
    t.pharmacy = sum(s.amount for s in session.sales.all())
    for rule in _rules_on(session.date):
        amount = round_fcfa(Decimal(t.lab) * rule.rate / 100)
        t.commissions[rule.name] = {"amount": amount, "retained": rule.retained, "beneficiary": rule.beneficiary}
        if rule.retained:
            t.commissions_retained += amount
        else:
            t.commissions_paid += amount
    for x in session.expenses.all():
        t.expenses_by_fund[x.fund] += x.amount
        t.expenses_by_category[x.category.name] += x.amount
    return t


def sessions_queryset(facility=None):
    facility = facility or Facility.current()
    return CashSession.objects.filter(facility=facility).prefetch_related(
        Prefetch("entries", queryset=ActEntry.objects.select_related("act")),
        Prefetch("expenses", queryset=Expense.objects.select_related("category")),
        "sales",
        Prefetch("visits", queryset=Visit.objects.filter(cancelled=False).prefetch_related(
            Prefetch("acts", queryset=VisitAct.objects.select_related("act")))),
    )


def period_sessions(start: date, end: date, facility=None):
    return list(sessions_queryset(facility).filter(date__gte=start, date__lte=end).order_by("date"))


def period_totals(start: date, end: date, facility=None):
    """Retourne (totaux de la période, [(session, totaux du jour), ...])."""
    total = Totals()
    days = []
    for s in period_sessions(start, end, facility):
        st = session_totals(s)
        total.add(st)
        days.append((s, st))
    return total, days


def deposits_total(start: date, end: date, facility=None, from_till=None) -> int:
    """Versements bancaires de la période ; from_till=True/False : seulement ceux faits depuis la caisse /
    depuis les remises reçues par le superviseur."""
    facility = facility or Facility.current()
    qs = Deposit.objects.filter(facility=facility, date__gte=start, date__lte=end)
    if from_till is not None:
        qs = qs.filter(from_till=from_till)
    return qs.aggregate(s=Sum("amount"))["s"] or 0


def handovers_total(start: date, end: date, facility=None) -> int:
    """Argent remis par le caissier au superviseur (journées validées de la période)."""
    facility = facility or Facility.current()
    return (CashSession.objects.filter(facility=facility, date__gte=start, date__lte=end)
            .aggregate(s=Sum("handed_over"))["s"] or 0)


def deposits_by_account(start: date, end: date, facility=None):
    facility = facility or Facility.current()
    rows = (Deposit.objects.filter(facility=facility, date__gte=start, date__lte=end)
            .values("account__id", "account__bank", "account__name").annotate(s=Sum("amount"))
            .order_by("account__bank"))
    return [{"account": r["account__bank"] if r["account__name"] == r["account__bank"]
             else f'{r["account__bank"]} – {r["account__name"]}', "amount": r["s"] or 0} for r in rows]


def _since_opening(upto: date, facility, include_day):
    start = facility.opening_date or date(2000, 1, 1)
    end = upto if include_day else upto - timedelta(days=1)
    return start, end


def cash_balance(upto: date, facility=None, include_day=True) -> int:
    """Argent qui devrait se trouver physiquement dans la caisse (chez le caissier) après la journée `upto`
    (ou le matin, si include_day=False) :
    argent au démarrage + recettes nettes − remises au superviseur − versements faits depuis la caisse."""
    facility = facility or Facility.current()
    start, end = _since_opening(upto, facility, include_day)
    if end < start:
        return facility.opening_cash
    total, _ = period_totals(start, end, facility)
    return (facility.opening_cash + total.net_total - handovers_total(start, end, facility)
            - deposits_total(start, end, facility, from_till=True))


def supervisor_balance(upto: date, facility=None, include_day=True) -> int:
    """Argent gardé par le superviseur, pas encore versé : remises reçues − versements faits par lui."""
    facility = facility or Facility.current()
    start, end = _since_opening(upto, facility, include_day)
    if end < start:
        return 0
    return handovers_total(start, end, facility) - deposits_total(start, end, facility, from_till=False)


def month_bounds(year: int, month: int):
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return start, end


def active_acts():
    return list(Act.objects.filter(active=True).order_by("name_key"))


def acts_for_display(totals_list=()):
    """Actes actifs + actes inactifs ayant des montants dans la période (pour les rapports)."""
    used = set()
    for t in totals_list:
        used.update(k for k, v in t.acts_amount.items() if v)
    qs = Act.objects.filter(active=True) | Act.objects.filter(id__in=used)
    return list(qs.distinct().order_by("name_key"))


def legacy_lab_act():
    """Acte « Laboratoire » des journées importées de l'ancien tableau Excel, où le laboratoire était un montant
    global par jour. Inactif : à la caisse, chaque examen est un acte avec son propre prix."""
    act, _ = Act.objects.get_or_create(code="laboratoire", defaults=dict(
        name="Laboratoire (import Excel)", category="LABO", fund=FUND_ENTREE, entry_mode=Act.MODE_AMOUNT,
        is_lab=True, active=False, order=900))
    return act


def ensure_entries(session: CashSession):
    """Crée les lignes d'actes manquantes (à zéro) pour la saisie."""
    existing = set(session.entries.values_list("act_id", flat=True))
    for act in Act.objects.filter(active=True).exclude(id__in=existing):
        ActEntry.objects.create(session=session, act=act, quantity=0,
                                unit_price=act.price_on(session.date) if act.by_quantity else None)


def daily_alerts(session: CashSession, totals: Totals):
    alerts = []
    if totals.net_entree < 0:
        alerts.append(
            "La caisse Entrées + Labo est négative ce jour : les dépenses dépassent les recettes de cette caisse."
        )
    if totals.net_pharma < 0:
        alerts.append("La caisse Pharmacie + Écho est négative ce jour.")
    for e in session.entries.all():
        if e.act.by_quantity and e.quantity and not e.unit_price:
            alerts.append(f"Aucun tarif défini pour « {e.act.name} » à cette date.")
    return alerts


def missing_days(start: date, end: date, facility=None):
    facility = facility or Facility.current()
    have = set(CashSession.objects.filter(facility=facility, date__gte=start, date__lte=end)
               .values_list("date", flat=True))
    out = []
    d = start
    while d <= end:
        if d not in have:
            out.append(d)
        d += timedelta(days=1)
    return out


def pharmacy_sales_total(start, end, facility=None):
    facility = facility or Facility.current()
    return PharmacySale.objects.filter(session__facility=facility, session__date__gte=start,
                                       session__date__lte=end).aggregate(s=Sum("amount"))["s"] or 0


# --- Passages patients et stock ---------------------------------------------------
def visit_act_totals(session: CashSession):
    """act_id -> (nombre, montant) des passages non annulés de la journée."""
    out = defaultdict(lambda: [0, 0])
    for line in VisitAct.objects.filter(visit__session=session, visit__cancelled=False):
        out[line.act_id][0] += line.quantity
        out[line.act_id][1] += line.amount
    return out


def product_stock(product_ids):
    from stock.models import StockMovement

    rows = (StockMovement.objects.filter(product_id__in=product_ids).values("product_id")
            .annotate(s=Sum("quantity")))
    return {r["product_id"]: r["s"] or 0 for r in rows}


class VisitError(Exception):
    pass


def save_visit(session, patient, act_lines, product_lines, user, visit=None):
    """Crée ou remplace un passage.

    patient : dict des champs du patient ; act_lines : [(Act, nombre, montant saisi ou None)] ;
    product_lines : [(Product, quantité, vendu par l'autre unité du produit (ex. plaquette))].
    Lève VisitError (liste de messages) si la saisie est invalide.
    """
    from django.db import transaction

    errors = []
    acts = []
    for act, qty, amount in act_lines:
        if act.by_quantity:
            price = act.price_on(session.date)
            if price is None:
                errors.append(f"Aucun tarif défini pour « {act.name} » à cette date (voir Paramètres).")
                continue
            acts.append((act, qty, price, qty * price))
        else:
            if not amount:
                errors.append(f"Indiquez le montant de « {act.name} ».")
                continue
            acts.append((act, 1, None, amount))

    lines = defaultdict(int)  # (produit, par l'autre unité) -> quantité vendue
    for product, qty, pack in product_lines:
        pack = pack and product.has_pack
        if not (product.pack_price if pack else product.sale_price):
            unit = f" par {product.pack_unit}" if pack else ""
            errors.append(f"Le prix de vente de « {product.name} »{unit} n'est pas défini (voir Stock).")
        lines[(product, pack)] += qty
    wanted = defaultdict(int)  # produit -> unités de stock
    for (product, pack), qty in lines.items():
        wanted[product] += qty * (product.pack_size if pack else 1)
    if session.facility.block_negative_stock and wanted:
        stock = product_stock([p.id for p in wanted])
        already = defaultdict(int)  # quantités déjà sur ce reçu (modification) : elles reviennent en stock
        if visit:
            for s in visit.sales.all():
                already[s.product_id] += s.stock_quantity
        for product, qty in wanted.items():
            available = stock.get(product.id, 0) + already[product.id]
            if qty > available:
                errors.append(f"Stock insuffisant pour « {product.name} » : {max(available, 0)} {product.unit}(s) "
                              "disponible(s). Si le stock réel est différent, faites un inventaire.")
    if not acts and not wanted:
        errors.append("Ajoutez au moins un produit." if patient.get("kind") == Visit.PHARMACY
                      else "Ajoutez au moins un acte ou un produit.")
    if errors:
        raise VisitError(errors)

    with transaction.atomic():
        if visit is None:
            visit = Visit(session=session, created_by=user, number=Visit.next_number(session.date))
        else:
            visit.acts.all().delete()
            visit.sales.all().delete()
        for field, value in patient.items():
            setattr(visit, field, value)
        visit.save()
        for act, qty, price, amount in acts:
            VisitAct.objects.create(visit=visit, act=act, quantity=qty, unit_price=price, amount=amount)
        for (product, pack), qty in lines.items():
            PharmacySale.objects.create(
                session=session, visit=visit, product=product, quantity=qty, pack=pack,
                units_per_item=product.pack_size if pack else 1,
                unit_price=product.pack_price if pack else product.sale_price, description=f"Reçu {visit.number}")
    return visit


def cancel_visit(visit, reason, user):
    from django.db import transaction
    from django.utils import timezone

    with transaction.atomic():
        visit.cancelled = True
        visit.cancel_reason = reason
        visit.cancelled_by = user
        visit.cancelled_at = timezone.now()
        visit.save()
        visit.sales.all().delete()  # les produits reviennent en stock
