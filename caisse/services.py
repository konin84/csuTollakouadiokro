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
                     Expense, PharmacySale)


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


def deposits_total(start: date, end: date, facility=None) -> int:
    facility = facility or Facility.current()
    return (Deposit.objects.filter(facility=facility, date__gte=start, date__lte=end)
            .aggregate(s=Sum("amount"))["s"] or 0)


def deposits_by_account(start: date, end: date, facility=None):
    facility = facility or Facility.current()
    rows = (Deposit.objects.filter(facility=facility, date__gte=start, date__lte=end)
            .values("account__id", "account__bank", "account__name").annotate(s=Sum("amount"))
            .order_by("account__bank"))
    return [{"account": r["account__bank"] if r["account__name"] == r["account__bank"]
             else f'{r["account__bank"]} – {r["account__name"]}', "amount": r["s"] or 0} for r in rows]


def cash_balance(upto: date, facility=None, include_day=True) -> int:
    """Argent qui devrait se trouver physiquement en caisse après la journée `upto`
    (ou le matin, si include_day=False) :
    argent au démarrage + recettes nettes − versements bancaires."""
    facility = facility or Facility.current()
    start = facility.opening_date or date(2000, 1, 1)
    end = upto if include_day else upto - timedelta(days=1)
    if end < start:
        return facility.opening_cash
    total, _ = period_totals(start, end, facility)
    return facility.opening_cash + total.net_total - deposits_total(start, end, facility)


def month_bounds(year: int, month: int):
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return start, end


def active_acts():
    return list(Act.objects.filter(active=True).order_by("order", "name"))


def acts_for_display(totals_list=()):
    """Actes actifs + actes inactifs ayant des montants dans la période (pour les rapports)."""
    used = set()
    for t in totals_list:
        used.update(k for k, v in t.acts_amount.items() if v)
    qs = Act.objects.filter(active=True) | Act.objects.filter(id__in=used)
    return list(qs.distinct().order_by("order", "name"))


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
