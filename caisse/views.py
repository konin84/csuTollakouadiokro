from datetime import date, datetime, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
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
from .forms import CloseForm, DepositForm, ExpenseForm, ReopenForm, SaleForm
from .models import FUND_ENTREE, FUND_LABELS, FUNDS, Act, ActEntry, CashSession, Deposit, Expense, ExpenseCategory, PharmacySale


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
    groups = []
    for e in entries:
        label = e.act.get_category_display()
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append(e)
    categories = list(ExpenseCategory.objects.filter(active=True))
    return {
        "session": session,
        "totals": totals,
        "groups": groups,
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
    get_object_or_404(PharmacySale, pk=pk, session=session).delete()
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
