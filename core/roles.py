"""Rôles de l'application (groupes Django) et droits associés.

Un utilisateur peut avoir plusieurs rôles. Le super-utilisateur (administrateur)
a tous les droits et accède aux paramètres.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

CAISSIER = "Caissier"
SUPERVISEUR = "Superviseur"
PHARMACIE = "Pharmacie"
CONSULTATION = "Consultation"

ALL_ROLES = [CAISSIER, SUPERVISEUR, PHARMACIE, CONSULTATION]

ROLE_HELP = {
    CAISSIER: "Saisit les recettes, dépenses et versements du jour, clôture la journée.",
    SUPERVISEUR: "Valide ou rouvre les journées, corrige les versements, voit le journal d'activité.",
    PHARMACIE: "Gère les produits, commandes, réceptions et inventaires ; saisit les ventes.",
    CONSULTATION: "Lecture seule : tableaux de bord et rapports (COGES, district…).",
}

# droit -> rôles autorisés
RIGHTS = {
    "saisie": {CAISSIER, SUPERVISEUR},
    "ventes": {CAISSIER, PHARMACIE, SUPERVISEUR},
    "cloture": {CAISSIER, SUPERVISEUR},
    "validation": {SUPERVISEUR},
    "versement": {CAISSIER, SUPERVISEUR},
    "versement_correction": {SUPERVISEUR},
    "stock": {PHARMACIE, SUPERVISEUR},
    "rapports": {CAISSIER, SUPERVISEUR, PHARMACIE, CONSULTATION},
    "journal": {SUPERVISEUR},
    "parametres": set(),  # administrateurs uniquement
}


def user_roles(user):
    if not user.is_authenticated:
        return set()
    cached = getattr(user, "_role_cache", None)
    if cached is None:
        cached = set(user.groups.values_list("name", flat=True))
        user._role_cache = cached
    return cached


def can(user, right: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return bool(user_roles(user) & RIGHTS.get(right, set()))


def require(right: str):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not can(request.user, right):
                raise PermissionDenied("Vous n'avez pas le droit d'effectuer cette action.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
