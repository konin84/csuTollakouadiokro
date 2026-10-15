"""Préparation des données des rapports (partagée entre l'écran et l'export Excel)."""
from collections import defaultdict

from caisse import services
from caisse.models import Deposit, Expense
from core.models import Facility

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
    expenses = list(Expense.objects.filter(session__facility=facility, session__date__range=(start, end))
                    .select_related("category", "session").order_by("session__date", "id"))
    deposits = list(Deposit.objects.filter(facility=facility, date__range=(start, end))
                    .select_related("account").order_by("date"))
    cash_start = services.cash_balance(start, facility, include_day=False)
    cash_end = services.cash_balance(end, facility)
    return {
        "facility": facility,
        "year": year, "month": month, "month_name": f"{MONTHS_FR[month - 1]} {year}",
        "start": start, "end": end,
        "total": total, "days": days, "acts": [x["act"] for x in activity], "activity": activity,
        "expenses": expenses,
        "expenses_by_category": sorted(total.expenses_by_category.items(), key=lambda kv: -kv[1]),
        "deposits": deposits, "deposits_total": sum(d.amount for d in deposits),
        "cash_start": cash_start, "cash_end": cash_end,
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
