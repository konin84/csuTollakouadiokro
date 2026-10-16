import mimetypes
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.utils import timezone

from caisse import services
from caisse.models import CashSession
from stock.models import Product, PurchaseOrder

from .models import AuditLog, Facility
from .roles import can, require, user_roles

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre"]


def dashboard(request):
    """Tableau de bord : partie caisse et partie pharmacie selon les droits de l'utilisateur."""
    today = timezone.localdate()
    context = {"today": today, "roles": sorted(user_roles(request.user))}
    if can(request.user, "caisse"):
        context.update(_cash_dashboard(request, today))
    if can(request.user, "pharmacie"):
        context.update(_stock_dashboard())
    return render(request, "core/dashboard.html", context)


def _stock_dashboard():
    products = list(Product.objects.filter(active=True).annotate(qty=Sum("movements__quantity")))
    return {
        "low_stock": [p for p in products if p.reorder_level > 0 and (p.qty or 0) <= p.reorder_level],
        "products_count": len(products),
        "out_of_stock": sum(1 for p in products if (p.qty or 0) <= 0),
        "stock_value": sum(p.stock_value(p.qty) for p in products),
        "orders_pending": PurchaseOrder.objects.filter(status=PurchaseOrder.ORDERED).count(),
    }


def _cash_dashboard(request, today):
    facility = Facility.current()
    start, end = services.month_bounds(today.year, today.month)
    month_total, month_days = services.period_totals(start, today)

    # même période le mois précédent
    prev_start = (start - timedelta(days=1)).replace(day=1)
    prev_end_full = start - timedelta(days=1)
    prev_end = prev_start.replace(day=min(today.day, prev_end_full.day))
    prev_total, _ = services.period_totals(prev_start, prev_end)

    today_session = CashSession.objects.filter(facility=facility, date=today).first()
    cash_now = services.cash_balance(today)

    alerts = []
    stale_open = CashSession.objects.filter(facility=facility, status=CashSession.OPEN, date__lt=today)
    for s in stale_open[:10]:
        alerts.append(("warn", f"La journée du {s.date:%d/%m/%Y} n'a pas été clôturée.", s.date))
    if can(request.user, "validation"):
        n = CashSession.objects.filter(facility=facility, status=CashSession.CLOSED).count()
        if n:
            first = CashSession.objects.filter(facility=facility, status=CashSession.CLOSED).order_by("date").first()
            alerts.append(("info", f"{n} journée(s) clôturée(s) : recevoir l'argent du caissier et valider.",
                           first.date))
    gaps = CashSession.objects.filter(facility=facility, date__gte=start, counted_cash__isnull=False,
                                      expected_cash__isnull=False)
    for s in gaps:
        if abs(s.cash_gap) > facility.cash_tolerance:
            alerts.append(("bad", f"Écart de caisse de {s.cash_gap:+,} F le {s.date:%d/%m/%Y}.".replace(",", " "),
                           s.date))
        if s.handover_gap:
            alerts.append(("bad", f"Le {s.date:%d/%m/%Y}, le superviseur a reçu {s.handover_gap:+,} F par rapport "
                                  "à l'argent compté à la clôture.".replace(",", " "), s.date))
    for s, t in month_days:
        if t.net_entree < 0:
            alerts.append(("warn", f"Le {s.date:%d/%m/%Y}, les dépenses dépassent les recettes de la caisse "
                                   f"Entrées + Labo ({t.net_entree:,} F).".replace(",", " "), s.date))

    # tendance : 12 derniers mois
    trend = []
    y, m = today.year, today.month
    for _ in range(12):
        s, e = services.month_bounds(y, m)
        t, _days = services.period_totals(s, min(e, today))
        trend.append({"label": f"{MONTHS_FR[m - 1][:4]}. {str(y)[2:]}", "net": t.net_total, "gross": t.gross,
                      "current": (y, m) == (today.year, today.month)})
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    trend.reverse()
    peak = max([t["gross"] for t in trend] + [1])
    for t in trend:
        t["pct_gross"] = round(100 * t["gross"] / peak, 1)
        t["pct_net"] = round(100 * max(t["net"], 0) / peak, 1)

    return {
        "month_name": f"{MONTHS_FR[today.month - 1]} {today.year}",
        "month_total": month_total,
        "prev_total": prev_total,
        "today_session": today_session,
        "cash_now": cash_now,
        "deposits_month": services.deposits_total(start, end),
        "handovers_month": services.handovers_total(start, end),
        "supervisor_cash": services.supervisor_balance(today),
        "alerts": alerts,
        "trend": trend,
    }


@require("journal")
def audit_log(request):
    qs = AuditLog.objects.select_related("user")
    q = request.GET.get("q", "").strip()
    action = request.GET.get("action", "")
    user_id = request.GET.get("utilisateur", "")
    if q:
        qs = qs.filter(Q(object_repr__icontains=q) | Q(model__icontains=q))
    if action:
        qs = qs.filter(action=action)
    if user_id:
        qs = qs.filter(user_id=user_id)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "core/audit_log.html", {
        "page": page, "q": q, "action": action, "user_id": user_id,
        "actions": AuditLog.ACTIONS, "users": User.objects.order_by("username"),
    })


def protected_media(request, path):
    """Les justificatifs ne sont accessibles qu'aux utilisateurs connectés."""
    root = Path(settings.MEDIA_ROOT).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise Http404
    ctype, _ = mimetypes.guess_type(str(target))
    return FileResponse(open(target, "rb"), content_type=ctype or "application/octet-stream")
