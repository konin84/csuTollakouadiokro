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
    CAISSIER: "Saisit les recettes et dépenses du jour et remet l'argent au superviseur le soir. "
              "Ne voit pas la pharmacie.",
    SUPERVISEUR: "Clôture la journée, reçoit l'argent du caissier en la validant et le verse à la banque ; "
                 "rouvre les journées, voit le journal d'activité.",
    PHARMACIE: "Gère les produits, commandes, réceptions et inventaires ; rapport de stock. Ne voit pas la caisse.",
    CONSULTATION: "Lecture seule : tableaux de bord et rapports (COGES, district…).",
}

# droit -> rôles autorisés
RIGHTS = {
    # consultation des pages : la caisse (journées, reçus) et la pharmacie (stock, commandes)
    # sont cloisonnées entre caissier et pharmacie ; le superviseur ne voit pas les pages de la pharmacie
    "caisse": {CAISSIER, SUPERVISEUR, CONSULTATION},
    "pharmacie": {PHARMACIE, CONSULTATION},
    "saisie": {CAISSIER},  # reçus des patients (« Nouveau patient »)
    "ouverture": {CAISSIER, SUPERVISEUR},  # ouvrir une journée de caisse
    "annulation": {CAISSIER, SUPERVISEUR},  # annuler un reçu, avec un motif
    "ventes": {CAISSIER},  # ventes de médicaments (bouton « Vente de médicaments »)
    "depenses": {SUPERVISEUR},  # dépenses payées en espèces : voir, ajouter, supprimer
    "cloture": {SUPERVISEUR},
    "validation": {SUPERVISEUR},
    "banque": {SUPERVISEUR, CONSULTATION},  # consultation des versements bancaires
    "versement": {SUPERVISEUR},
    "versement_correction": {SUPERVISEUR},
    "stock": {PHARMACIE},
    "rapports": {CAISSIER, SUPERVISEUR, CONSULTATION},  # rapports de caisse (mensuel, annuel)
    "rapport_stock": {PHARMACIE, SUPERVISEUR, CONSULTATION},  # le superviseur suit le stock sans gérer la pharmacie
    "journal": {SUPERVISEUR},
    "actes": {SUPERVISEUR},  # actes médicaux et tarifs : créer, modifier, supprimer
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
