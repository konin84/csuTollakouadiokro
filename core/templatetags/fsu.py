import os

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static

from core.roles import can as can_right

register = template.Library()

NBSP = " "  # espace fine insécable (séparateur de milliers français)


def _group(n: int) -> str:
    s = f"{abs(int(n)):,}".replace(",", NBSP)
    return ("-" if n < 0 else "") + s


@register.filter
def fcfa(value, suffix=True):
    """1224851 -> '1 224 851 F'"""
    if value in (None, ""):
        return "—"
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return value
    return _group(n) + (f"{NBSP}F" if suffix else "")


@register.filter
def num(value):
    """Nombre avec séparateur de milliers, sans unité ; vide si 0/None."""
    if value in (None, "", 0):
        return ""
    try:
        return _group(int(round(float(value))))
    except (TypeError, ValueError):
        return value


@register.filter
def num0(value):
    """Comme num mais affiche 0."""
    if value in (None, ""):
        return "0"
    try:
        return _group(int(round(float(value))))
    except (TypeError, ValueError):
        return value


@register.filter
def get(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        try:
            return mapping[key]
        except Exception:
            return None


@register.simple_tag(takes_context=True)
def can(context, right):
    return can_right(context["request"].user, right)


@register.filter
def sub(value, other):
    try:
        return (value or 0) - (other or 0)
    except TypeError:
        return value


@register.filter
def neg(value):
    try:
        return float(value) < 0
    except (TypeError, ValueError):
        return False


@register.simple_tag
def asset(path):
    """URL d'un fichier statique. En développement, ?v=<date de modification> force le navigateur à recharger
    le fichier modifié (en production, le nom du fichier contient déjà une empreinte)."""
    url = static(path)
    if settings.DEBUG:
        found = finders.find(path)
        if found:
            url += f"?v={int(os.path.getmtime(found))}"
    return url


@register.filter
def stock_describe(qty, product):
    """Stock en unités d'achat : 1 045 comprimés -> « 10 boîte(s) + 45 comprimé(s) »."""
    return product.describe(qty or 0)
