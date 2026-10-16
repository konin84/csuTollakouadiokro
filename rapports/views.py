from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core.roles import require

from . import data, excel

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _month_param(request):
    today = timezone.localdate()
    try:
        y, m = (int(x) for x in request.GET.get("mois", f"{today:%Y-%m}").split("-"))
        if not 1 <= m <= 12:
            raise ValueError
    except ValueError:
        y, m = today.year, today.month
    return y, m


def _year_param(request):
    try:
        return int(request.GET.get("annee") or timezone.localdate().year)
    except ValueError:
        return timezone.localdate().year


@require("rapports")
def monthly(request):
    y, m = _month_param(request)
    ctx = data.monthly(y, m)
    ctx["detail"] = request.GET.get("vue") == "detail"
    ctx["prev"] = f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}"
    ctx["next"] = f"{y + (m == 12)}-{m % 12 + 1:02d}"
    ctx["mois"] = f"{y}-{m:02d}"
    return render(request, "rapports/monthly.html", ctx)


@require("rapports")
def monthly_xlsx(request):
    y, m = _month_param(request)
    content = excel.monthly_workbook(data.monthly(y, m))
    resp = HttpResponse(content, content_type=XLSX)
    resp["Content-Disposition"] = f'attachment; filename="rapport-mensuel-{y}-{m:02d}.xlsx"'
    return resp


@require("rapports")
def annual(request):
    y = _year_param(request)
    ctx = data.annual(y)
    peak = max([r["t"].gross for r in ctx["rows"]] + [1])
    for r in ctx["rows"]:
        r["pct"] = round(100 * r["t"].gross / peak, 1)
        r["pct_net"] = round(100 * max(r["t"].net_total, 0) / peak, 1)
    return render(request, "rapports/annual.html", ctx)


@require("rapports")
def annual_xlsx(request):
    y = _year_param(request)
    resp = HttpResponse(excel.annual_workbook(data.annual(y)), content_type=XLSX)
    resp["Content-Disposition"] = f'attachment; filename="rapport-annuel-{y}.xlsx"'
    return resp


@require("rapport_stock")
def stock(request):
    y, m = _month_param(request)
    ctx = data.stock_monthly(y, m)
    ctx["prev"] = f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}"
    ctx["next"] = f"{y + (m == 12)}-{m % 12 + 1:02d}"
    ctx["mois"] = f"{y}-{m:02d}"
    return render(request, "rapports/stock.html", ctx)


@require("rapport_stock")
def stock_xlsx(request):
    y, m = _month_param(request)
    resp = HttpResponse(excel.stock_workbook(data.stock_monthly(y, m)), content_type=XLSX)
    resp["Content-Disposition"] = f'attachment; filename="rapport-stock-{y}-{m:02d}.xlsx"'
    return resp
