from datetime import date, datetime, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpResponse, JsonResponse
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
from .forms import (CancelVisitForm, CloseForm, DepositForm, ExpenseForm, ReopenForm, ValidateForm,
                    VisitForm)
from .models import (FUND_ENTREE, FUND_LABELS, FUNDS, Act, CashSession, Deposit, Expense, ExpenseCategory,
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


DAY_ROWS_PER_PAGE = 10  # patients, ventes et dépenses de la journée : 10 lignes par page


def _day_nav(day):
    """Navigation entre journées : le jour précédent, et un retour à aujourd'hui (si on n'y est pas déjà)."""
    today = timezone.localdate()
    return {"prev_day": day - timedelta(days=1), "today_day": today if day != today else None}


def _session_context(request, session):
    totals = services.session_totals(session)
    morning = services.cash_balance(session.date, include_day=False)
    deposits_today = list(Deposit.objects.filter(facility=session.facility, date=session.date, from_till=True)
                          .select_related("account"))
    dep_total = sum(d.amount for d in deposits_today)
    expected = morning + totals.net_total - dep_total
    cat_rank = {code: i for i, (code, _label) in enumerate(Act.CATEGORIES)}
    entries = sorted(session.entries.all(), key=lambda e: (cat_rank.get(e.act.category, 99), e.act.name_key))
    from_visits = services.visit_act_totals(session)
    groups = []
    for e in entries:
        e.visit_qty, e.visit_amount = from_visits.get(e.act_id, (0, 0))
        # quantités de la grille : journées importées d'Excel ou saisies avant les reçus patients
        e.total_qty = e.quantity + e.visit_qty
        e.total_amount = e.amount + e.visit_amount
        label = e.act.get_category_display()
        if not groups or groups[-1]["label"] != label:
            groups.append({"label": label, "code": e.act.category, "entries": [], "total": 0, "count": 0})
        groups[-1]["entries"].append(e)
        groups[-1]["total"] += e.total_amount
        groups[-1]["count"] += e.total_qty if e.act.by_quantity else (1 if e.total_amount else 0)
    categories = list(ExpenseCategory.objects.filter(active=True))
    visits = list(Visit.objects.filter(session=session).select_related("created_by")
                  .prefetch_related("acts__act", "sales__product"))
    by_cashier = {}
    for v in visits:
        if v.cancelled:
            continue
        name = (v.created_by.get_full_name() or v.created_by.username) if v.created_by else "—"
        row = by_cashier.setdefault(name, {"name": name, "count": 0, "amount": 0})
        row["count"] += 1
        row["amount"] += v.total
    return {
        "session": session,
        "totals": totals,
        "groups": groups,
        "visits_page": Paginator(visits[::-1], DAY_ROWS_PER_PAGE).get_page(request.GET.get("patients")),
        "sales_page": Paginator(list(session.sales.select_related("product").order_by("-id")), DAY_ROWS_PER_PAGE)
        .get_page(request.GET.get("ventes")),
        "expenses_page": Paginator(list(session.expenses.select_related("category").order_by("-id")),
                                   DAY_ROWS_PER_PAGE).get_page(request.GET.get("depenses")),
        "session_url": reverse("session_detail", args=[f"{session.date:%Y-%m-%d}"]),
        "by_cashier": sorted(by_cashier.values(), key=lambda r: r["name"]),
        "editable": _editable(request, session),
        "can_sell": session.is_open and can(request.user, "ventes"),
        "can_spend": session.is_open and can(request.user, "depenses"),
        "expense_form": ExpenseForm(initial={"fund": FUND_ENTREE}),
        "category_funds": {c.id: c.default_fund for c in categories},
        "fund_labels": FUND_LABELS,
        "morning_cash": morning,
        "deposits_today": deposits_today,
        "deposits_today_total": dep_total,
        "expected_cash": expected,
        "alerts": services.daily_alerts(session, totals),
        "close_form": CloseForm(initial={"notes": session.notes}),
        "reopen_form": ReopenForm(),
        **_day_nav(session.date),
        "tolerance": session.facility.cash_tolerance,
    }


# ---------------------------------------------------------------------------
@require("caisse")
def session_list(request):
    today = timezone.localdate()
    try:
        year, month = (int(x) for x in request.GET.get("mois", f"{today:%Y-%m}").split("-"))
        start, end = services.month_bounds(year, month)
    except ValueError:
        start, end = services.month_bounds(today.year, today.month)
    if start > today:  # pas de mois futur
        start, end = services.month_bounds(today.year, today.month)
    total, days = services.period_totals(start, end)
    prev_month = (start - timedelta(days=1)).replace(day=1)
    next_month = end + timedelta(days=1)
    if next_month > today:
        next_month = None
    missing = [d for d in services.missing_days(start, min(end, today))]
    return render(request, "caisse/session_list.html", {
        "start": start, "end": end, "days": days, "total": total,
        "prev_month": prev_month, "next_month": next_month, "today": today,
        "missing": missing,
    })


@require_POST
@require("ouverture")
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


@require("caisse")
def session_today(request):
    today = timezone.localdate()
    session = CashSession.objects.filter(facility=Facility.current(), date=today).first()
    if session:
        return redirect("session_detail", day=f"{today:%Y-%m-%d}")
    return render(request, "caisse/session_missing.html", {"day": today, **_day_nav(today)})


@require("caisse")
def session_detail(request, day):
    d = _parse_day(day)
    if d > timezone.localdate():  # pas de journée future
        return redirect("session_detail", day=f"{timezone.localdate():%Y-%m-%d}")
    session = CashSession.objects.filter(facility=Facility.current(), date=d).first()
    if session is None:
        return render(request, "caisse/session_missing.html", {"day": d, **_day_nav(d)})
    if session.is_open and can(request.user, "ouverture"):
        services.ensure_entries(session)
    session = _get_session(day)
    return render(request, "caisse/session_detail.html", _session_context(request, session))


def _section_response(request, session, template):
    session = _get_session(f"{session.date:%Y-%m-%d}")
    ctx = _session_context(request, session)
    html = render_to_string(template, ctx, request=request)
    summary = render_to_string("caisse/_summary.html", {**ctx, "oob": True}, request=request)
    return HttpResponse(html + summary)


@require_POST
def expense_add(request, day):
    session = _get_session(day)
    if not _editable(request, session, "depenses"):
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
    if not _editable(request, session, "depenses"):
        raise PermissionDenied
    get_object_or_404(Expense, pk=pk, session=session).delete()
    return _section_response(request, session, "caisse/_expenses.html")


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
        messages.success(request, "Journée clôturée. Recevez l'argent du caissier et validez la journée.")
    return redirect("session_detail", day=day)


@require_POST
@require("validation")
def session_validate(request, day):
    session = _get_session(day)
    if session.status != CashSession.CLOSED:
        messages.error(request, "Seule une journée clôturée peut être validée.")
        return redirect("session_detail", day=day)
    form = ValidateForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Indiquez l'argent reçu du caissier.")
        return redirect("session_detail", day=day)
    session.status = CashSession.VALIDATED
    session.validated_by = request.user
    session.validated_at = timezone.now()
    session.handed_over = form.cleaned_data["handed_over"]
    session._audit_skip = True
    session.save()
    log("validate", session, {"argent compté": session.counted_cash, "argent reçu": session.handed_over,
                              "écart de remise": session.handover_gap})
    gap = session.handover_gap or 0
    if gap:
        messages.warning(request, f"Journée validée. L'argent reçu diffère de {gap:+,} F de l'argent compté "
                                  "à la clôture.".replace(",", " "))
    else:
        messages.success(request, f"Journée validée : {session.handed_over:,} F reçus du caissier."
                         .replace(",", " "))
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
    # handed_over est conservé : l'argent est déjà chez le superviseur ; la nouvelle validation le remplace
    session._audit_skip = True
    session.save()
    log("reopen", session, {"motif": form.cleaned_data["reason"], "statut précédent": previous})
    messages.info(request, "Journée rouverte : les corrections sont tracées dans le journal d'activité.")
    return redirect("session_detail", day=day)


# ---------------------------------------------------------------------------
@require("banque")
def deposit_list(request):
    today = timezone.localdate()
    year = services.requested_year(request.GET.get("annee"))
    years = services.year_choices()
    if year not in years:
        years = sorted(set(years) | {year}, reverse=True)
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
        months.append({"start": start, "net": total.net_total, "handed_over": services.handovers_total(start, end),
                       "deposited": dep, "by_fund": total.net_by_fund()})
    return render(request, "caisse/deposit_list.html", {
        "deposits": deposits, "form": form, "year": year, "years": years, "months": months,
        "cash_now": services.cash_balance(today), "supervisor_cash": services.supervisor_balance(today),
        "today": today,
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
    for a in sorted(acts, key=lambda a: (cat_rank.get(a.category, 99), a.name_key)):
        label = a.get_category_display()
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append({"id": a.id, "name": a.name, "by_quantity": a.by_quantity,
                              "price": a.price_on(session.date)})
    products = [{"id": p.id, "name": p.name, "code": p.code, "unit": p.unit, "price": p.sale_price,
                 "stock": p.qty or 0,
                 "pack_unit": p.pack_unit if p.has_pack else "", "pack_size": p.pack_size or 1,
                 "pack_price": p.pack_price}
                for p in Product.objects.filter(active=True).annotate(qty=Sum("movements__quantity"))]
    return groups, products


def _parse_lines(request):
    """Lignes du formulaire : act / act_qty / act_amount et product / product_qty (listes parallèles)."""
    post = request.POST
    act_ids, act_qtys, act_amounts = post.getlist("act"), post.getlist("act_qty"), post.getlist("act_amount")
    prod_ids, prod_qtys, prod_units = post.getlist("product"), post.getlist("product_qty"), post.getlist("product_unit")
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
        pack = i < len(prod_units) and prod_units[i] == "pack"
        rows["products"].append({"id": product.id, "qty": qty, "unit": "pack" if pack else "unite"})
        if qty < 1:
            errors.append(f"Quantité invalide pour « {product.name} ».")
            continue
        product_lines.append((product, qty, pack))
    return act_lines, product_lines, rows, errors


def _visit_form(request, session, visit, pharmacy=False):
    """Reçu d'un patient (actes et produits) ou, avec pharmacy=True, vente de médicaments seule."""
    form = VisitForm(request.POST or None, instance=visit, pharmacy=pharmacy)
    errors = []
    if request.method == "POST":
        act_lines, product_lines, rows, errors = _parse_lines(request)
        if pharmacy:
            act_lines = []
        if form.is_valid() and not errors:
            patient = {f: form.cleaned_data[f] for f in VisitForm.Meta.fields}
            patient["kind"] = Visit.PHARMACY if pharmacy else Visit.PATIENT
            try:
                saved = services.save_visit(session, patient, act_lines, product_lines, request.user, visit=visit)
            except services.VisitError as e:
                errors = e.args[0]
            else:
                messages.success(request, f"Reçu {saved.number} enregistré pour {saved.patient_name}.")
                return redirect("visit_receipt", day=f"{session.date:%Y-%m-%d}", pk=saved.pk)
    elif visit:
        rows = {"acts": [{"id": a.act_id, "qty": a.quantity, "amount": a.amount} for a in visit.acts.all()],
                "products": [{"id": s.product_id, "qty": s.quantity, "unit": "pack" if s.pack else "unite"}
                             for s in visit.sales.all()]}
    elif pharmacy:
        rows = {"acts": [], "products": [{"id": "", "qty": 1, "unit": "unite"}]}
    else:
        rows = {"acts": [{"id": "", "qty": 1, "amount": ""}], "products": []}
    act_groups, products = _visit_choices(session, visit)
    return render(request, "caisse/visit_form.html", {
        "session": session, "visit": visit, "form": form, "errors": errors, "rows": rows,
        "act_groups": act_groups, "products": products, "pharmacy": pharmacy,
        "block_stock": session.facility.block_negative_stock,
    })


def visit_new(request, day):
    session = _get_session(day)
    if not _editable(request, session):
        raise PermissionDenied
    return _visit_form(request, session, None)


def pharmacy_sale_new(request, day):
    """Client venu seulement pour des médicaments : reçu sans actes."""
    session = _get_session(day)
    if not _editable(request, session, "ventes"):
        raise PermissionDenied
    return _visit_form(request, session, None, pharmacy=True)


def visit_edit(request, day, pk):
    session = _get_session(day)
    visit = get_object_or_404(Visit, pk=pk, session=session)
    right = "ventes" if visit.is_pharmacy else "saisie"
    if not _editable(request, session, right) or visit.cancelled:
        raise PermissionDenied
    return _visit_form(request, session, visit, pharmacy=visit.is_pharmacy)


@require("caisse")
def visit_receipt(request, day, pk):
    session = _get_session(day)
    visit = get_object_or_404(Visit.objects.select_related("created_by", "cancelled_by")
                              .prefetch_related("acts__act", "sales__product"), pk=pk, session=session)
    right = "ventes" if visit.is_pharmacy else "saisie"
    return render(request, "caisse/visit_receipt.html", {
        "session": session, "visit": visit, "cancel_form": CancelVisitForm(),
        "editable": _editable(request, session, right) and not visit.cancelled,     # modifier, reçu suivant
        "can_cancel": _editable(request, session, "annulation") and not visit.cancelled,
    })


@require_POST
def visit_cancel(request, day, pk):
    session = _get_session(day)
    visit = get_object_or_404(Visit, pk=pk, session=session, cancelled=False)
    if not _editable(request, session, "annulation"):
        raise PermissionDenied
    form = CancelVisitForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Indiquez le motif de l'annulation.")
        return redirect("visit_receipt", day=day, pk=pk)
    services.cancel_visit(visit, form.cleaned_data["reason"], request.user)
    log("cancel", visit, {"motif": form.cleaned_data["reason"]})
    messages.info(request, f"Reçu {visit.number} annulé : les produits sont remis en stock.")
    return redirect("session_detail", day=day)


@require("saisie")
def patient_search(request):
    """Patients déjà venus, retrouvés par le nom (3 lettres) ou le téléphone (4 chiffres)."""
    q = " ".join(request.GET.get("q", "").split())
    digits = "".join(ch for ch in q if ch.isdigit())
    if len(q) < 3:
        return JsonResponse({"patients": []})
    cond = Q(patient_name__icontains=q)
    if len(digits) >= 4:
        cond |= Q(phone__contains=digits)
    today = timezone.localdate()
    found = {}
    for v in Visit.objects.filter(cond, cancelled=False).select_related("session").order_by("-id")[:300]:
        key = (v.patient_name.upper(), v.phone)
        if key in found:
            found[key]["visits"] += 1
            continue
        if len(found) >= 8:
            continue
        found[key] = {
            "name": v.patient_name, "phone": v.phone, "sex": v.sex,
            # âge mis à jour depuis le dernier passage (approximation à l'année)
            "age": v.age + (today.year - v.session.date.year) if v.age is not None else None,
            "last": f"{v.session.date:%d/%m/%Y}", "visits": 1,
        }
    return JsonResponse({"patients": list(found.values())})
