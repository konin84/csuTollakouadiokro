from django import forms
from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.utils.text import slugify

from caisse.forms import DateInput
from caisse.models import Act, ActPrice, BankAccount, CommissionRule, ExpenseCategory, name_key
from core.models import Facility
from core.roles import ALL_ROLES, ROLE_HELP
from stock.models import Supplier


class FacilityForm(forms.ModelForm):
    class Meta:
        model = Facility
        fields = ["name", "short_name", "address", "phone", "opening_date", "opening_cash", "cash_tolerance",
                  "block_negative_stock"]
        widgets = {"opening_date": DateInput()}


# --- Utilisateurs ------------------------------------------------------------
class UserForm(forms.ModelForm):
    roles = forms.MultipleChoiceField(
        label="Rôles", required=False, widget=forms.CheckboxSelectMultiple,
        choices=[(r, f"{r} — {ROLE_HELP[r]}") for r in ALL_ROLES],
    )
    password1 = forms.CharField(label="Mot de passe", widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label="Confirmer le mot de passe", widget=forms.PasswordInput, strip=False)

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "is_superuser", "is_active"]
        labels = {"username": "Identifiant", "first_name": "Prénom", "last_name": "Nom",
                  "is_superuser": "Administrateur", "is_active": "Compte actif"}
        help_texts = {
            "username": "Utilisé pour se connecter. Lettres, chiffres et . @ + - _ uniquement.",
            "is_superuser": "Tous les droits, y compris les paramètres et la gestion des utilisateurs.",
            "is_active": "Décocher pour bloquer la connexion sans perdre l'historique de la personne.",
        }

    def __init__(self, *args, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_user = current_user
        if self.instance.pk:
            del self.fields["password1"], self.fields["password2"]
            self.initial["roles"] = list(self.instance.groups.values_list("name", flat=True))
        else:
            self.initial.setdefault("is_active", True)

    def clean(self):
        data = super().clean()
        user = self.instance
        if user.pk and user == self.current_user:
            if not data.get("is_active"):
                self.add_error("is_active", "Vous ne pouvez pas désactiver votre propre compte.")
            if user.is_superuser and not data.get("is_superuser"):
                self.add_error("is_superuser", "Vous ne pouvez pas retirer vos propres droits d'administrateur.")
        if user.pk and user.is_superuser and not (data.get("is_superuser") and data.get("is_active")):
            others = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=user.pk)
            if not others.exists():
                raise forms.ValidationError("Il doit rester au moins un administrateur actif.")
        if "password1" in self.fields:
            p1, p2 = data.get("password1"), data.get("password2")
            if p1 and p2 and p1 != p2:
                self.add_error("password2", "Les deux mots de passe sont différents.")
            elif p1:
                try:
                    validate_password(p1, user)
                except forms.ValidationError as e:
                    self.add_error("password1", e)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        if not user.pk:
            user.set_password(self.cleaned_data["password1"])
        user.save()
        user.groups.set(Group.objects.filter(name__in=self.cleaned_data["roles"]))
        return user


# --- Actes et tarifs -----------------------------------------------------------
class ActForm(forms.ModelForm):
    price = forms.IntegerField(label="Prix unitaire (F)", min_value=0, required=False)
    valid_from = forms.DateField(label="Applicable à partir du", required=False, widget=DateInput())

    class Meta:
        model = Act
        fields = ["name", "category", "fund", "is_lab", "active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            del self.fields["price"], self.fields["valid_from"]  # tarifs suivants : panneau « Tarifs »
        else:
            # chaque acte a un prix fixe (nombre × prix unitaire)
            self.fields["price"].required = self.fields["valid_from"].required = True

    def clean_name(self):
        """Un seul acte par libellé (accents, majuscules et espaces ignorés)."""
        name = " ".join(self.cleaned_data["name"].split())
        same = Act.objects.filter(name_key=name_key(name)).exclude(pk=self.instance.pk).first()
        if same:
            hint = " (désactivé : rouvrez-le et cochez « Actif »)" if not same.active else ""
            raise forms.ValidationError(f"L'acte « {same.name} » existe déjà{hint}.")
        return name

    def save(self, commit=True):
        act = super().save(commit=False)
        if not act.pk:
            base = slugify(act.name)[:34] or "acte"
            code, n = base, 2
            while Act.objects.filter(code=code).exists():
                code, n = f"{base}-{n}", n + 1
            act.code = code
        act.save()
        if self.cleaned_data.get("price") is not None and self.cleaned_data.get("valid_from"):
            ActPrice.objects.create(act=act, price=self.cleaned_data["price"],
                                    valid_from=self.cleaned_data["valid_from"])
        return act


class ActPriceForm(forms.ModelForm):
    class Meta:
        model = ActPrice
        fields = ["price", "valid_from"]
        widgets = {"valid_from": DateInput()}

    def __init__(self, *args, act=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.act = act

    def clean_valid_from(self):
        day = self.cleaned_data["valid_from"]
        if ActPrice.objects.filter(act=self.act, valid_from=day).exists():
            raise forms.ValidationError("Un tarif existe déjà à cette date.")
        return day


# --- Listes simples -------------------------------------------------------------
class CommissionRuleForm(forms.ModelForm):
    class Meta:
        model = CommissionRule
        fields = ["name", "beneficiary", "rate", "retained", "valid_from", "valid_to", "order"]
        widgets = {"valid_from": DateInput(), "valid_to": DateInput()}

    def clean(self):
        data = super().clean()
        start, end = data.get("valid_from"), data.get("valid_to")
        if start and end and end < start:
            self.add_error("valid_to", "La date de fin est avant la date de début.")
        return data


class ExpenseCategoryForm(forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ["name", "default_fund", "order", "active"]


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ["bank", "name", "number", "fund", "active"]


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "phone", "address"]
