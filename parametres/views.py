"""Paramètres de l'application, sans passer par l'administration Django.

Réservé aux administrateurs, sauf les fournisseurs (droit « stock »).
"""
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from caisse.models import Act, ActEntry, ActPrice, BankAccount, CommissionRule, ExpenseCategory, name_key
from core.audit import log
from core.models import Facility
from core.roles import can, require
from stock.models import Supplier

from .forms import (ActForm, ActPriceForm, BankAccountForm, CommissionRuleForm, ExpenseCategoryForm,
                    FacilityForm, SupplierForm, UserForm)


def _yes_no(value):
    return "Oui" if value else "Non"


def _pct(value):
    """Decimal("12.50") -> "12,5 %"."""
    return f"{float(value):g} %".replace(".", ",")


def _day(value):
    return f"{value:%d/%m/%Y}" if value else "—"


def _commission_notice():
    today = timezone.localdate()
    total = CommissionRule.active_on(today).aggregate(s=Sum("rate"))["s"] or 0
    if total != 100:
        return (f"Les règles applicables aujourd'hui totalisent {_pct(total)} au lieu de 100 % : "
                "une partie de la recette laboratoire n'est pas répartie.")
    return None


# Listes simples : un seul gabarit de liste et un seul de formulaire.
SIMPLE = {
    "commissions": {
        "model": CommissionRule, "form": CommissionRuleForm, "right": "parametres",
        "title": "Commissions laboratoire", "new": "Nouvelle règle",
        "intro": "Répartition de la recette laboratoire. Pour changer un taux, terminez l'ancienne règle "
                 "(date de fin) et créez-en une nouvelle : les journées passées gardent l'ancien taux.",
        "columns": [("Libellé", lambda o: o.name), ("Bénéficiaire", lambda o: o.beneficiary or "—"),
                    ("Taux", lambda o: _pct(o.rate)),
                    ("Conservé en caisse", lambda o: _yes_no(o.retained)),
                    ("Du", lambda o: _day(o.valid_from)), ("Au", lambda o: _day(o.valid_to))],
        "notice": _commission_notice,
    },
    "categories": {
        "model": ExpenseCategory, "form": ExpenseCategoryForm, "right": "parametres",
        "title": "Catégories de dépenses", "new": "Nouvelle catégorie",
        "intro": "Une catégorie qui ne sert plus peut être désactivée : elle reste dans l'historique.",
        "columns": [("Libellé", lambda o: o.name), ("Caisse par défaut", lambda o: o.get_default_fund_display()),
                    ("Ordre", lambda o: o.order), ("Active", lambda o: _yes_no(o.active))],
    },
    "banques": {
        "model": BankAccount, "form": BankAccountForm, "right": "parametres",
        "title": "Comptes bancaires", "new": "Nouveau compte",
        "intro": "Comptes sur lesquels les versements sont faits.",
        "columns": [("Banque", lambda o: o.bank), ("Libellé", lambda o: o.name), ("N° de compte", lambda o: o.number),
                    ("Caisse", lambda o: o.get_fund_display() or "Les deux"), ("Actif", lambda o: _yes_no(o.active))],
    },
    "fournisseurs": {
        "model": Supplier, "form": SupplierForm, "right": "stock",
        "title": "Fournisseurs", "new": "Nouveau fournisseur",
        "intro": "Fournisseurs proposés sur les commandes de la pharmacie.",
        "columns": [("Nom", lambda o: o.name), ("Téléphone", lambda o: o.phone), ("Adresse", lambda o: o.address)],
    },
}


def _simple_config(request, kind):
    conf = SIMPLE.get(kind)
    if conf is None:
        raise Http404
    if not can(request.user, conf["right"]):
        raise PermissionDenied("Vous n'avez pas le droit d'effectuer cette action.")
    return conf


def simple_list(request, kind):
    conf = _simple_config(request, kind)
    rows = [(obj, [fn(obj) for _, fn in conf["columns"]]) for obj in conf["model"].objects.all()]
    return render(request, "parametres/simple_list.html", {
        "conf": conf, "kind": kind, "headers": [h for h, _ in conf["columns"]], "rows": rows,
        "notice": conf["notice"]() if conf.get("notice") else None,
    })


def simple_edit(request, kind, pk=None):
    conf = _simple_config(request, kind)
    obj = get_object_or_404(conf["model"], pk=pk) if pk else None
    form = conf["form"](request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"« {saved} » enregistré.")
        return redirect("param_list", kind=kind)
    return render(request, "parametres/simple_form.html", {"conf": conf, "kind": kind, "form": form, "obj": obj})


# --- Accueil et établissement ---------------------------------------------------
@require("parametres")
def index(request):
    return render(request, "parametres/index.html", {
        "nb_users": User.objects.filter(is_active=True).count(),
        "nb_acts": Act.objects.filter(active=True).count(),
        "nb_rules": CommissionRule.active_on(timezone.localdate()).count(),
        "nb_categories": ExpenseCategory.objects.filter(active=True).count(),
        "nb_accounts": BankAccount.objects.filter(active=True).count(),
        "nb_suppliers": Supplier.objects.count(),
        "commission_notice": _commission_notice(),
    })


@require("parametres")
def facility(request):
    form = FacilityForm(request.POST or None, instance=Facility.current())
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Établissement enregistré.")
        return redirect("param_index")
    return render(request, "parametres/facility.html", {"form": form})


# --- Utilisateurs -----------------------------------------------------------------
def _user_state(user):
    return {
        "identifiant": user.username, "nom": user.get_full_name(), "administrateur": _yes_no(user.is_superuser),
        "actif": _yes_no(user.is_active), "rôles": ", ".join(sorted(user.groups.values_list("name", flat=True))),
    }


@require("parametres")
def user_list(request):
    users = User.objects.prefetch_related("groups").order_by("-is_active", "username")
    return render(request, "parametres/user_list.html", {"users": users})


@require("parametres")
def user_edit(request, pk=None):
    user = get_object_or_404(User, pk=pk) if pk else None
    before = _user_state(user) if user else None
    form = UserForm(request.POST or None, instance=user, current_user=request.user)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        after = _user_state(saved)
        if before is None:
            log("create", saved, {"valeurs": after}, model="utilisateur", object_repr=saved.username)
            messages.success(request, f"Compte « {saved.username} » créé.")
        else:
            changes = {k: [before[k], v] for k, v in after.items() if before[k] != v}
            if changes:
                log("update", saved, {"modifications": changes}, model="utilisateur", object_repr=saved.username)
            messages.success(request, f"Compte « {saved.username} » enregistré.")
        return redirect("param_users")
    password_form = SetPasswordForm(user) if user else None
    return render(request, "parametres/user_form.html", {"form": form, "obj": user, "password_form": password_form})


@require_POST
@require("parametres")
def user_password(request, pk):
    user = get_object_or_404(User, pk=pk)
    form = SetPasswordForm(user, request.POST)
    if form.is_valid():
        form.save()
        if user == request.user:
            update_session_auth_hash(request, user)
        log("update", user, {"modifications": {"mot de passe": ["", "réinitialisé"]}}, model="utilisateur",
            object_repr=user.username)
        messages.success(request, f"Mot de passe de « {user.username} » changé.")
        return redirect("param_users")
    return render(request, "parametres/user_form.html", {
        "form": UserForm(instance=user, current_user=request.user), "obj": user, "password_form": form,
    })


# --- Actes et tarifs ------------------------------------------------------------------
@require("actes")
def act_list(request):
    today = timezone.localdate()
    q = request.GET.get("q", "").strip()
    acts = Act.objects.prefetch_related("prices")
    if q:  # accents et majuscules ignorés : « echo » trouve « Échographie »
        acts = acts.filter(name_key__contains=name_key(q))
    acts = list(acts)
    for act in acts:
        current = [p for p in act.prices.all() if p.valid_from <= today]
        act.current_price = current[0].price if current else None
        act.next_price = next((p for p in reversed(act.prices.all()) if p.valid_from > today), None)
    return render(request, "parametres/act_list.html", {"acts": acts, "q": q})


@require("actes")
def act_edit(request, pk=None):
    act = get_object_or_404(Act, pk=pk) if pk else None
    form = ActForm(request.POST or None, instance=act,
                   initial=None if act else {"valid_from": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"Acte « {saved.name} » enregistré.")
        return redirect("param_act", pk=saved.pk) if act is None else redirect("param_acts")
    ctx = {"form": form, "obj": act}
    if act:
        ctx["prices"] = act.prices.all()
        ctx["price_form"] = ActPriceForm(act=act, initial={"valid_from": timezone.localdate()})
        ctx["today"] = timezone.localdate()
    return render(request, "parametres/act_form.html", ctx)


@require_POST
@require("actes")
def act_price_add(request, pk):
    act = get_object_or_404(Act, pk=pk)
    form = ActPriceForm(request.POST, act=act)
    if form.is_valid():
        price = form.save(commit=False)
        price.act = act
        price.save()
        messages.success(request, f"Nouveau tarif : {price.price} F à partir du {price.valid_from:%d/%m/%Y}.")
        return redirect("param_act", pk=pk)
    return render(request, "parametres/act_form.html", {
        "form": ActForm(instance=act), "obj": act, "prices": act.prices.all(), "price_form": form,
        "today": timezone.localdate(),
    })


@require_POST
@require("actes")
def act_price_delete(request, pk, price_id):
    price = get_object_or_404(ActPrice, pk=price_id, act_id=pk)
    if price.valid_from <= timezone.localdate():
        messages.error(request, "Un tarif déjà appliqué ne peut pas être supprimé : ajoutez plutôt un nouveau tarif.")
    else:
        price.delete()
        messages.success(request, "Tarif à venir supprimé.")
    return redirect("param_act", pk=pk)


@require_POST
@require("actes")
def act_delete(request, pk):
    """Supprime un acte jamais utilisé ; un acte déjà facturé se désactive (l'historique reste juste)."""
    act = get_object_or_404(Act, pk=pk)
    if act.has_been_charged():
        messages.error(request, f"« {act.name} » a déjà été facturé : il ne peut pas être supprimé. "
                                "Décochez « Actif » pour ne plus le proposer.")
        return redirect("param_act", pk=pk)
    with transaction.atomic():
        ActEntry.objects.filter(act=act).delete()  # lignes vides des journées
        act.delete()
    messages.success(request, f"Acte « {act.name} » supprimé.")
    return redirect("param_acts")
