"""Préparation des données des rapports (partagée entre l'écran et l'export Excel)."""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Q, Sum
from django.utils import timezone

from caisse import services
from caisse.models import Deposit, Expense, PharmacySale
from core.models import Facility
from stock.models import Product, StockMovement

MONTHS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre",
             "Novembre", "Décembre"]


def monthly(year: int, month: int):
    facility = Facility.current()
    start, end = services.month_bounds(year, month)
    total, days = services.period_totals(start, end, facility)
    acts = services.acts_for_display([total])
    activity = []
    for a in acts:
        qty = total.acts_qty.get(a.id, 0)
        amount = total.acts_amount.get(a.id, 0)
        if not a.active and not amount:
            continue
        activity.append({"act": a, "qty": qty, "amount": amount,
                         "price": a.price_on(end) if a.by_quantity else None})
    # détail par jour, sans défilement horizontal : chaque jour du mois (jusqu'à aujourd'hui), avec seulement les
    # actes réalisés ; un jour sans journée de caisse est signalé « non saisie » (fermé ou oublié ?)
    by_date = {s.date: (s, t) for s, t in days}
    first = max(start, facility.opening_date) if facility.opening_date else start
    last = min(end, timezone.localdate())
    day_details = []
    d = first
    while d <= last:
        s, t = by_date.get(d, (None, None))
        lines = []
        if t:
            lines = [{"act": a, "qty": t.acts_qty.get(a.id, 0), "amount": t.acts_amount.get(a.id, 0)}
                     for a in acts if t.acts_amount.get(a.id, 0)]
            for line in lines:
                line["price"] = line["amount"] // line["qty"] if line["act"].by_quantity and line["qty"] else None
        day_details.append({"date": d, "session": s, "totals": t, "lines": lines})
        d += timedelta(days=1)
    expenses = list(Expense.objects.filter(session__facility=facility, session__date__range=(start, end))
                    .select_related("category", "session").order_by("session__date", "id"))
    deposits = list(Deposit.objects.filter(facility=facility, date__range=(start, end))
                    .select_related("account").order_by("date"))
    # argent pas encore versé à la banque : dans la caisse + chez le superviseur
    cash_start = (services.cash_balance(start, facility, include_day=False)
                  + services.supervisor_balance(start, facility, include_day=False))
    till_end = services.cash_balance(end, facility)
    supervisor_end = services.supervisor_balance(end, facility)
    return {
        "facility": facility,
        "year": year, "month": month, "month_name": f"{MONTHS_FR[month - 1]} {year}",
        "start": start, "end": end,
        "total": total, "days": days, "day_details": day_details,
        "days_entered": sum(1 for x in day_details if x["session"]), "days_listed": len(day_details),
        "acts": [x["act"] for x in activity], "activity": activity,
        "expenses": expenses,
        "expenses_by_category": sorted(total.expenses_by_category.items(), key=lambda kv: -kv[1]),
        "deposits": deposits, "deposits_total": sum(d.amount for d in deposits),
        "cash_start": cash_start, "cash_end": till_end + supervisor_end,
        "till_end": till_end, "supervisor_end": supervisor_end,
    }


def annual(year: int):
    facility = Facility.current()
    rows = []
    grand = services.Totals()
    acts_months = defaultdict(lambda: [0] * 12)
    exp_months = defaultdict(lambda: [0] * 12)
    for m in range(1, 13):
        start, end = services.month_bounds(year, m)
        t, _ = services.period_totals(start, end, facility)
        dep = services.deposits_total(start, end, facility)
        grand.add(t)
        rows.append({"month": m, "name": MONTHS_FR[m - 1], "t": t, "deposits": dep})
        for act_id, q in t.acts_qty.items():
            acts_months[act_id][m - 1] += q
        for cat, amount in t.expenses_by_category.items():
            exp_months[cat][m - 1] += amount
    acts = services.acts_for_display([grand])
    activity = [{"act": a, "months": acts_months[a.id], "total": sum(acts_months[a.id]),
                 "amount": grand.acts_amount.get(a.id, 0)} for a in acts
                if a.active or grand.acts_amount.get(a.id)]
    expenses = sorted(([cat, vals, sum(vals)] for cat, vals in exp_months.items()), key=lambda r: -r[2])
    return {
        "facility": facility, "year": year, "rows": rows, "grand": grand,
        "deposits_total": sum(r["deposits"] for r in rows),
        "activity": activity, "expenses": expenses, "month_names": [m[:4] + "." for m in MONTHS_FR],
    }


# colonnes du rapport de stock : type de mouvement -> colonne
STOCK_COLUMNS = {
    StockMovement.INITIAL: "entries", StockMovement.RECEPTION: "entries", StockMovement.ENTRY: "entries",
    StockMovement.SALE: "sold", StockMovement.LOSS: "lost",
    StockMovement.ADJUST: "adjusted",
}


def stock_monthly(year: int, month: int):
    """Mouvements de stock du mois par produit (en unités de stock) : stock au début, entrées, sorties,
    ajustements, stock à la fin. Les valeurs sont au dernier prix d'achat (stock, pertes) et au prix de vente réel
    des ventes du mois (ventes à l'unité ou par plaquette)."""
    facility = Facility.current()
    start, end = services.month_bounds(year, month)
    in_month = Q(movements__date__range=(start, end))
    products = Product.objects.annotate(
        opening=Sum("movements__quantity", filter=Q(movements__date__lt=start)),
        moved=Sum("movements__quantity", filter=in_month),
    )
    per_kind = defaultdict(dict)
    for r in (StockMovement.objects.filter(date__range=(start, end))
              .values("product_id", "kind").annotate(q=Sum("quantity"))):
        per_kind[r["product_id"]][r["kind"]] = r["q"]
    sales = dict(PharmacySale.objects.filter(session__facility=facility, session__date__range=(start, end),
                                             product__isnull=False)
                 .values_list("product_id").annotate(s=Sum("amount")))

    rows = []
    totals = defaultdict(int)
    for p in products:
        kinds = per_kind.get(p.id, {})
        if not (p.active or p.opening or kinds):
            continue
        row = {"product": p, "opening": p.opening or 0, "entries": 0, "sold": 0, "lost": 0,
               "adjusted": 0}
        for kind, q in kinds.items():
            col = STOCK_COLUMNS[kind]
            # sorties affichées en positif ; les ajustements gardent leur signe
            row[col] += q if col in ("entries", "adjusted") else -q
        row["closing"] = row["opening"] + (p.moved or 0)
        row["sales_value"] = sales.get(p.id, 0)
        row["lost_value"] = round(row["lost"] * p.unit_cost)
        row["closing_value"] = p.stock_value(row["closing"])
        row["low"] = p.active and p.reorder_level > 0 and row["closing"] <= p.reorder_level
        rows.append(row)
        for k in ("opening", "entries", "sold", "lost", "adjusted", "closing", "sales_value",
                  "lost_value", "closing_value"):
            totals[k] += row[k]

    details = (StockMovement.objects.filter(date__range=(start, end),
                                            kind__in=[StockMovement.RECEPTION, StockMovement.ENTRY,
                                                      StockMovement.LOSS, StockMovement.ADJUST])
               .select_related("product", "created_by").order_by("date", "id"))
    return {
        "facility": facility,
        "year": year, "month": month, "month_name": f"{MONTHS_FR[month - 1]} {year}",
        "start": start, "end": end,
        "rows": rows, "totals": totals,
        "low": [r for r in rows if r["low"]],
        "out": [r for r in rows if r["product"].active and r["closing"] <= 0],
        "entries": [m for m in details if m.kind in (StockMovement.RECEPTION, StockMovement.ENTRY)],
        "losses": [m for m in details if m.kind == StockMovement.LOSS],
        "adjustments": [m for m in details if m.kind == StockMovement.ADJUST],
    }
