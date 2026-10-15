from datetime import date, datetime, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log
from core.models import Facility
from core.roles import can, require
from stock.models import Product

from . import services
from .forms import CancelVisitForm, CloseForm, DepositForm, ExpenseForm, ReopenForm, SaleForm, VisitForm
from .models import (FUND_ENTREE, FUND_LABELS, FUNDS, Act, ActEntry, CashSession, Deposit, Expense, ExpenseCategory,
                     PharmacySale, Visit)


def _parse_day(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return timezone.localdate()


def _get_session(day_str):
    day = _parse_day(day_str)
    session = (services.sessions_queryset().filter(date=day).first())
    if session is None:
        from django.http import Http404

        raise Http404("Journée introuvable")
    return session


def _editable(request, session, right="saisie"):
    return session.is_open and can(request.user, right)


def _session_context(request, session):
    totals = services.session_totals(session)
    morning = services.cash_balance(session.date, include_day=False)
    deposits_today = list(Deposit.objects.filter(facility=session.facility, date=session.date)
                          .select_related("account"))
    dep_total = sum(d.amount for d in deposits_today)
    expected = morning + totals.net_total - dep_total
    cat_rank = {code: i for i, (code, _label) in enumerate(Act.CATEGORIES)}
    entries = sorted(session.entries.all(), key=lambda e: (cat_rank.get(e.act.category, 99), e.act.order, e.act.name))
    from_visits = services.visit_act_totals(session)
    groups = []
    for e in entries:
        e.visit_qty, e.visit_amount = from_visits.get(e.act_id, (0, 0))
        e.total_amount = e.amount + e.visit_amount
        label = e.act.get_category_display()
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append(e)
    categories = list(ExpenseCategory.objects.filter(active=True))
    return {
        "session": session,
        "totals": totals,
        "groups": groups,
        "visits": Visit.objects.filter(session=session).select_related("created_by")
                  .prefetch_related("acts__act", "sales__product"),
        "editable": _editable(request, session),
        "can_sell": session.is_open and can(request.user, "ventes"),
        "expense_form": ExpenseForm(initial={"fund": FUND_ENTREE}),
        "sale_form": SaleForm(initial={"quantity": 1}),
        "category_funds": {c.id: c.default_fund for c in categories},
        "product_prices": dict(Product.objects.filter(active=True).values_list("id", "sale_price")),
        "fund_labels": FUND_LABELS,
        "morning_cash": morning,
        "deposits_today": deposits_today,
        "deposits_today_total": dep_total,
        "expected_cash": expected,
        "alerts": services.daily_alerts(session, totals),
        "close_form": CloseForm(initial={"notes": session.notes}),
        "reopen_form": ReopenForm(),
        "prev_day": session.date - timedelta(days=1),
        "next_day": session.date + timedelta(days=1),
        "tolerance": session.facility.cash_tolerance,
    }


# ---------------------------------------------------------------------------
def session_list(request):
    today = timezone.localdate()
    try:
        year, month = (int(x) for x in request.GET.get("mois", f"{today:%Y-%m}").split("-"))
        start, end = services.month_bounds(year, month)
    except ValueError:
        start, end = services.month_bounds(today.year, today.month)
    total, days = services.period_totals(start, end)
    prev_month = (start - timedelta(days=1)).replace(day=1)
    next_month = end + timedelta(days=1)
    missing = [d for d in services.missing_days(start, min(end, today))]
    return render(request, "caisse/session_list.html", {
        "start": start, "end": end, "days": days, "total": total,
        "prev_month": prev_month, "next_month": next_month, "today": today,
        "missing": missing,
    })


@require_POST
@require("saisie")
def session_open(request):
    day = _parse_day(request.POST.get("date"))
    if day > timezone.localdate():
        messages.error(request, "Impossible d'ouvrir une journée future.")
        return redirect("session_list")
    facility = Facility.current()
    session, created = CashSession.objects.get_or_create(
        facility=facility, date=day, defaults={"opened_by": request.user})
    if created:
        services.ensure_entries(session)
        messages.success(request, f"Journée du {day:%d/%m/%Y} ouverte.")
    return redirect("session_detail", day=f"{day:%Y-%m-%d}")


def session_today(request):
    today = timezone.localdate()
    session = CashSession.objects.filter(facility=Facility.current(), date=today).first()
    if session:
        return redirect("session_detail", day=f"{today:%Y-%m-%d}")
    return render(request, "caisse/session_missing.html", {"day": today})


def session_detail(request, day):
    d = _parse_day(day)
    session = CashSession.objects.filter(facility=Facility.current(), date=d).first()
    if session is None:
        return render(request, "caisse/session_missing.html", {"day": d})
    if session.is_open and can(request.user, "saisie"):
        services.ensure_entries(session)
    session = _get_session(day)
    return render(request, "caisse/session_detail.html", _session_context(request, session))


def _summary_response(request, session, extra_html=""):
    session = _get_session(f"{session.date:%Y-%m-%d}")
    ctx = _session_context(request, session)
    html = render_to_string("caisse/_summary.html", ctx, request=request)
    return HttpResponse(extra_html + html)


@require_POST
def entry_update(request, day, entry_id):
    session = _get_session(day)
    if not _editable(request, session):
        raise PermissionDenied
    entry = get_object_or_404(ActEntry, pk=entry_id, session=session)
    raw = (request.POST.get("value") or "0").replace(" ", "").replace(" ", "")
    try:
        value = max(0, int(float(raw)))
    except ValueError:
        value = 0
    if entry.act.by_quantity:
        entry.quantity = value
        entry.manual_amount = False
        entry.unit_price = entry.unit_price or entry.act.price_on(session.date) or 0
    else:
        entry.amount = value
        entry.manual_amount = True
    entry.save()
    services.sync_consumption(session, entry.act)
    entry.total_amount = entry.amount + services.visit_act_totals(session)[entry.act_id][1]
    cell = render_to_string("caisse/_entry_amount.html", {"e": entry, "oob": True}, request=request)
    return _summary_response(request, session, cell)


def _section_response(request, session, template):
    session = _get_session(f"{session.date:%Y-%m-%d}")
    ctx = _session_context(request, session)
    html = render_to_string(template, ctx, request=request)
    summary = render_to_string("caisse/_summary.html", {**ctx, "oob": True}, request=request)
    return HttpResponse(html + summary)


@require_POST
def expense_add(request, day):
    session = _get_session(day)
    if not _editable(request, session):
        raise PermissionDenied
    form = ExpenseForm(request.POST, request.FILES)
    if form.is_valid():
        x = form.save(commit=False)
        x.session = session
        x.created_by = request.user
        x.save()
        return _section_response(request, session, "caisse/_expenses.html")
    ctx = _session_context(request, session)
    ctx["expense_form"] = form
    return HttpResponse(render_to_string("caisse/_expenses.html", ctx, request=request))


@require_POST
def expense_delete(request, day, pk):
    session = _get_session(day)
    if not _editable(request, session):
        raise PermissionDenied
    get_object_or_404(Expense, pk=pk, session=session).delete()
    return _section_response(request, session, "caisse/_expenses.html")


@require_POST
def sale_add(request, day):
    session = _get_session(day)
    if not (session.is_open and can(request.user, "ventes")):
        raise PermissionDenied
    form = SaleForm(request.POST)
    if form.is_valid():
        s = form.save(commit=False)
        s.session = session
        s.unit_price = form.cleaned_data["unit_price"] or 0
        s.description = form.cleaned_data.get("description") or ""
        s.save()
        return _section_response(request, session, "caisse/_sales.html")
    ctx = _session_context(request, session)
    ctx["sale_form"] = form
    return HttpResponse(render_to_string("caisse/_sales.html", ctx, request=request))


@require_POST
def sale_delete(request, day, pk):
    session = _get_session(day)
    if not (session.is_open and can(request.user, "ventes")):
        raise PermissionDenied
    get_object_or_404(PharmacySale, pk=pk, session=session, visit__isnull=True).delete()
    return _section_response(request, session, "caisse/_sales.html")


@require_POST
@require("cloture")
def session_close(request, day):
    session = _get_session(day)
    if not session.is_open:
        messages.error(request, "Cette journée n'est pas ouverte.")
        return redirect("session_detail", day=day)
    form = CloseForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Indiquez l'argent compté dans la caisse.")
        return redirect("session_detail", day=day)
    ctx = _session_context(request, session)
    with transaction.atomic():
        session.counted_cash = form.cleaned_data["counted_cash"]
        session.expected_cash = ctx["expected_cash"]
        session.notes = form.cleaned_data["notes"]
        session.status = CashSession.CLOSED
        session.closed_by = request.user
        session.closed_at = timezone.now()
        session._audit_skip = True
        session.save()
        log("close", session, {"argent compté": session.counted_cash, "solde théorique": session.expected_cash,
                               "écart": session.cash_gap, "recette nette": ctx["totals"].net_total})
    gap = session.cash_gap or 0
    if abs(gap) > session.facility.cash_tolerance:
        messages.warning(request, f"Journée clôturée avec un écart de caisse de {gap:+,} F.".replace(",", " "))
    else:
        messages.success(request, "Journée clôturée. Elle doit maintenant être validée par le superviseur.")
    return redirect("session_detail", day=day)


@require_POST
@require("validation")
def session_validate(request, day):
    session = _get_session(day)
    if session.status != CashSession.CLOSED:
        messages.error(request, "Seule une journée clôturée peut être validée.")
        return redirect("session_detail", day=day)
    session.status = CashSession.VALIDATED
    session.validated_by = request.user
    session.validated_at = timezone.now()
    session._audit_skip = True
    session.save()
    log("validate", session)
    messages.success(request, "Journée validée et verrouillée.")
    return redirect("session_detail", day=day)


@require_POST
@require("validation")
def session_reopen(request, day):
    session = _get_session(day)
    form = ReopenForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Le motif de réouverture est obligatoire.")
        return redirect("session_detail", day=day)
    previous = session.get_status_display()
    session.status = CashSession.OPEN
    session.validated_by = None
    session.validated_at = None
    session._audit_skip = True
    session.save()
    log("reopen", session, {"motif": form.cleaned_data["reason"], "statut précédent": previous})
    messages.info(request, "Journée rouverte : les corrections sont tracées dans le journal d'activité.")
    return redirect("session_detail", day=day)


# ---------------------------------------------------------------------------
def deposit_list(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get("annee") or today.year)
    except ValueError:
        year = today.year
    deposits = Deposit.objects.filter(facility=Facility.current(), date__year=year).select_related("account")
    form = None
    if can(request.user, "versement"):
        form = DepositForm(initial={"date": today})
    months = []
    for m in range(1, 13):
        start, end = services.month_bounds(year, m)
        if start > today:
            break
        total, _ = services.period_totals(start, end)
        dep = services.deposits_total(start, end)
        months.append({"start": start, "net": total.net_total, "deposited": dep,
                       "by_fund": total.net_by_fund()})
    return render(request, "caisse/deposit_list.html", {
        "deposits": deposits, "form": form, "year": year, "months": months,
        "cash_now": services.cash_balance(today), "today": today,
        "fund_labels": FUND_LABELS, "funds": FUNDS,
    })


@require_POST
@require("versement")
def deposit_add(request):
    form = DepositForm(request.POST, request.FILES)
    if form.is_valid():
        d = form.save(commit=False)
        d.facility = Facility.current()
        d.created_by = request.user
        d.save()
        messages.success(request, f"Versement de {d.amount:,} F enregistré.".replace(",", " "))
    else:
        messages.error(request, "Versement non enregistré : " + "; ".join(
            f"{form.fields[k].label if k in form.fields else k} : {' '.join(v)}" for k, v in form.errors.items()))
    return redirect(reverse("deposit_list") + f"?annee={request.POST.get('date', '')[:4] or ''}")


def deposit_edit(request, pk):
    deposit = get_object_or_404(Deposit, pk=pk)
    if not can(request.user, "versement_correction"):
        raise PermissionDenied
    form = DepositForm(request.POST or None, request.FILES or None, instance=deposit)
    if request.method == "POST":
        if "delete" in request.POST:
            deposit.delete()
            messages.info(request, "Versement supprimé (tracé dans le journal).")
            return redirect("deposit_list")
        if form.is_valid():
            form.save()
            messages.success(request, "Versement modifié.")
            return redirect("deposit_list")
    return render(request, "caisse/deposit_edit.html", {"form": form, "deposit": deposit})


# --- Passages patients -------------------------------------------------------------
def _int(raw, default=None):
    try:
        return int(str(raw).replace(" ", "").replace(" ", "").replace("\xa0", ""))
    except (TypeError, ValueError):
        return default


def _visit_choices(session, visit=None):
    """Actes (groupés par catégorie, avec le tarif du jour) et produits (prix, stock) proposés."""
    used = set(visit.acts.values_list("act_id", flat=True)) if visit else set()
    acts = (Act.objects.filter(active=True) | Act.objects.filter(id__in=used)).distinct()
    cat_rank = {code: i for i, (code, _label) in enumerate(Act.CATEGORIES)}
    groups = []
    for a in sorted(acts, key=lambda a: (cat_rank.get(a.category, 99), a.order, a.name)):
        label = a.get_category_display()
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append({"id": a.id, "name": a.name, "by_quantity": a.by_quantity,
                              "price": a.price_on(session.date)})
    products = [{"id": p.id, "name": p.name, "unit": p.unit, "price": p.sale_price, "stock": p.qty or 0}
                for p in Product.objects.filter(active=True).annotate(qty=Sum("movements__quantity"))]
    return groups, products


def _parse_lines(request):
    """Lignes du formulaire : act / act_qty / act_amount et product / product_qty (listes parallèles)."""
    post = request.POST
    act_ids, act_qtys, act_amounts = post.getlist("act"), post.getlist("act_qty"), post.getlist("act_amount")
    prod_ids, prod_qtys = post.getlist("product"), post.getlist("product_qty")
    acts = Act.objects.in_bulk([i for i in (_int(x) for x in act_ids) if i])
    products = Product.objects.in_bulk([i for i in (_int(x) for x in prod_ids) if i])
    act_lines, product_lines, errors = [], [], []
    rows = {"acts": [], "products": []}
    for i, raw in enumerate(act_ids):
        act = acts.get(_int(raw))
        if act is None:
            continue
        qty = _int(act_qtys[i] if i < len(act_qtys) else 1, 0)
        amount = _int(act_amounts[i] if i < len(act_amounts) else 0, 0)
        rows["acts"].append({"id": act.id, "qty": qty, "amount": amount})
        if qty < 1 or amount < 0:
            errors.append(f"Nombre ou montant invalide pour « {act.name} ».")
            continue
        act_lines.append((act, qty, amount))
    for i, raw in enumerate(prod_ids):
        product = products.get(_int(raw))
        if product is None:
            continue
        qty = _int(prod_qtys[i] if i < len(prod_qtys) else 1, 0)
        rows["products"].append({"id": product.id, "qty": qty})
        if qty < 1:
            errors.append(f"Quantité invalide pour « {product.name} ».")
            continue
        product_lines.append((product, qty))
    return act_lines, product_lines, rows, errors


def _visit_form(request, session, visit):
    form = VisitForm(request.POST or None, instance=visit)
    errors = []
    if request.method == "POST":
        act_lines, product_lines, rows, errors = _parse_lines(request)
        if form.is_valid() and not errors:
            patient = {f: form.cleaned_data[f] for f in VisitForm.Meta.fields}
            try:
                saved = services.save_visit(session, patient, act_lines, product_lines, request.user, visit=visit)
            except services.VisitError as e:
                errors = e.args[0]
            else:
                messages.success(request, f"Reçu {saved.number} enregistré pour {saved.patient_name}.")
                return redirect("visit_receipt", day=f"{session.date:%Y-%m-%d}", pk=saved.pk)
    elif visit:
        rows = {"acts": [{"id": a.act_id, "qty": a.quantity, "amount": a.amount} for a in visit.acts.all()],
                "products": [{"id": s.product_id, "qty": s.quantity} for s in visit.sales.all()]}
    else:
        rows = {"acts": [{"id": "", "qty": 1, "amount": ""}], "products": []}
    act_groups, products = _visit_choices(session, visit)
    return render(request, "caisse/visit_form.html", {
        "session": session, "visit": visit, "form": form, "errors": errors, "rows": rows,
        "act_groups": act_groups, "products": products,
        "block_stock": session.facility.block_negative_stock,
    })


def visit_new(request, day):
    session = _get_session(day)
    if not _editable(request, session):
        raise PermissionDenied
    return _visit_form(request, session, None)


def visit_edit(request, day, pk):
    session = _get_session(day)
    visit = get_object_or_404(Visit, pk=pk, session=session)
    if not _editable(request, session) or visit.cancelled:
        raise PermissionDenied
    return _visit_form(request, session, visit)


def visit_receipt(request, day, pk):
    session = _get_session(day)
    visit = get_object_or_404(Visit.objects.select_related("created_by", "cancelled_by")
                              .prefetch_related("acts__act", "sales__product"), pk=pk, session=session)
    return render(request, "caisse/visit_receipt.html", {
        "session": session, "visit": visit, "editable": _editable(request, session) and not visit.cancelled,
        "cancel_form": CancelVisitForm(),
    })


@require_POST
def visit_cancel(request, day, pk):
    session = _get_session(day)
    visit = get_object_or_404(Visit, pk=pk, session=session, cancelled=False)
    if not _editable(request, session):
        raise PermissionDenied
    form = CancelVisitForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Indiquez le motif de l'annulation.")
        return redirect("visit_receipt", day=day, pk=pk)
    services.cancel_visit(visit, form.cleaned_data["reason"], request.user)
    log("cancel", visit, {"motif": form.cleaned_data["reason"]})
    messages.info(request, f"Reçu {visit.number} annulé : les produits sont remis en stock.")
    return redirect("session_detail", day=day)
