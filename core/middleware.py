import threading
from urllib.parse import unquote, urlencode

from django.shortcuts import redirect

_local = threading.local()


class VercelPathMiddleware:
    """Sur Vercel, vercel.json réécrit toutes les adresses vers /api/index?__path=/<chemin d'origine>.

    Django reçoit donc /api/index comme chemin : on rétablit le chemin d'origine (sinon toutes les
    pages, connexion comprise, tournent en boucle de redirection). Sans __path, rien ne change.
    """

    PARAM = "__path"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        query = request.META.get("QUERY_STRING", "")
        if self.PARAM + "=" in query:
            kept, original = [], None
            for part in query.split("&"):
                name, _, value = part.partition("=")
                if name == self.PARAM:
                    original = unquote(value.replace("+", "%20"))
                elif part:
                    kept.append(part)
            if original is not None:
                path = original if original.startswith("/") else "/" + original
                request.path = request.path_info = path
                request.META["PATH_INFO"] = path
                request.META["QUERY_STRING"] = "&".join(kept)
                request.__dict__.pop("GET", None)  # QueryDict recalculé à partir du nouveau QUERY_STRING
        return self.get_response(request)


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
