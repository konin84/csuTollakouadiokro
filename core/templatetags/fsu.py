from django import template

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
