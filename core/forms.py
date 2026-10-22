from django import forms


class TrimTextMixin:
    """Champs texte d'une ligne : espaces retirés en début et fin, espaces répétés réduits à un seul
    (« Jean   Kouassi » -> « Jean Kouassi »). Fait avant les clean_<champ>() et clean() du formulaire.

    Les zones de texte (retours à la ligne voulus) et les mots de passe ne sont pas modifiés.
    À placer avant forms.Form / forms.ModelForm : class MonForm(TrimTextMixin, forms.ModelForm).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():  # champs copiés pour chaque formulaire : aucun effet global
            if (isinstance(field, forms.CharField)
                    and not isinstance(field.widget, (forms.Textarea, forms.PasswordInput))):
                field.to_python = _collapsing(field.to_python)


def _collapsing(to_python):
    def wrapped(value):
        value = to_python(value)
        return " ".join(value.split()) if isinstance(value, str) else value
    return wrapped
