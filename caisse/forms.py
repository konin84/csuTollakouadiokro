from django import forms

from core.forms import TrimTextMixin

from .models import BankAccount, Deposit, Expense, ExpenseCategory, Visit


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class ExpenseForm(TrimTextMixin, forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["category", "fund", "amount", "description", "beneficiary", "receipt"]
        widgets = {
            "amount": forms.NumberInput(attrs={"min": 1, "step": 1, "inputmode": "numeric"}),
            "description": forms.TextInput(attrs={"placeholder": "Ex. achat de 3 paquets de rame"}),
            "beneficiary": forms.TextInput(attrs={"placeholder": "Facultatif"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = ExpenseCategory.objects.filter(active=True)
        self.fields["receipt"].widget.attrs["accept"] = "image/*,application/pdf"


class DepositForm(TrimTextMixin, forms.ModelForm):
    class Meta:
        model = Deposit
        fields = ["date", "account", "amount", "reference", "depositor", "slip", "note"]
        widgets = {
            "date": DateInput(),
            "amount": forms.NumberInput(attrs={"min": 1, "step": 1, "inputmode": "numeric"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = BankAccount.objects.filter(active=True)
        self.fields["slip"].widget.attrs["accept"] = "image/*,application/pdf"


class CloseForm(TrimTextMixin, forms.Form):
    counted_cash = forms.IntegerField(label="Argent compté dans la caisse (F)", min_value=0,
                                      widget=forms.NumberInput(attrs={"inputmode": "numeric", "step": 1}))
    notes = forms.CharField(label="Observations", required=False,
                            widget=forms.Textarea(attrs={"rows": 2}))


class ValidateForm(TrimTextMixin, forms.Form):
    handed_over = forms.IntegerField(label="Argent reçu du caissier (F)", min_value=0,
                                     widget=forms.NumberInput(attrs={"inputmode": "numeric", "step": 1}))


class ReopenForm(TrimTextMixin, forms.Form):
    reason = forms.CharField(label="Motif de la réouverture", max_length=255)


class VisitForm(TrimTextMixin, forms.ModelForm):
    class Meta:
        model = Visit
        fields = ["patient_name", "phone", "sex", "age"]
        widgets = {
            "patient_name": forms.TextInput(attrs={"autofocus": True, "autocomplete": "off",
                                                   "placeholder": "Ex. KOUASSI Amenan Marie"}),
            "phone": forms.TextInput(attrs={"inputmode": "tel", "placeholder": "Facultatif"}),
            "age": forms.NumberInput(attrs={"min": 0, "max": 130, "inputmode": "numeric"}),
        }

    def clean_phone(self):
        # chiffres uniquement (et + initial) : la recherche par téléphone ne dépend pas des espaces
        raw = self.cleaned_data["phone"].strip()
        return ("+" if raw.startswith("+") else "") + "".join(ch for ch in raw if ch.isdigit())

    WALK_IN = "Client de passage"

    def __init__(self, *args, pharmacy=False, **kwargs):
        super().__init__(*args, **kwargs)
        # vente de médicaments seule : le nom du client est facultatif
        self.pharmacy = pharmacy
        if pharmacy:
            field = self.fields["patient_name"]
            field.required = False
            field.label = "Nom du client (facultatif)"
            field.widget.attrs["placeholder"] = self.WALK_IN

    def clean_patient_name(self):
        name = " ".join(self.cleaned_data["patient_name"].split())
        if self.pharmacy and not name:
            return self.WALK_IN
        if len(name) < 2:
            raise forms.ValidationError("Indiquez le nom du patient.")
        return name


class CancelVisitForm(TrimTextMixin, forms.Form):
    reason = forms.CharField(label="Motif de l'annulation", max_length=255)
