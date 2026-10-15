import threading
from urllib.parse import urlencode

from django.shortcuts import redirect

_local = threading.local()


def get_current_user():
    user = getattr(_local, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


class CurrentUserMiddleware:
    """Mémorise l'utilisateur de la requête pour le journal d'activité."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.user = getattr(request, "user", None)
        try:
            return self.get_response(request)
        finally:
            _local.user = None


class LoginRequiredMiddleware:
    """Toute l'application exige une connexion, sauf la page de connexion et les fichiers statiques."""

    OPEN_PREFIXES = ("/connexion", "/static/", "/admin/login", "/favicon")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not request.path.startswith(self.OPEN_PREFIXES):
            return redirect(f"/connexion/?{urlencode({'next': request.get_full_path()})}")
        return self.get_response(request)
