"""Point d'entrée Vercel : expose l'application WSGI Django.

vercel.json réécrit toutes les adresses vers /api/index?__path=/<chemin d'origine>. La fonction reçoit
donc /api/index comme chemin : on remet le chemin d'origine avant de passer la requête à Django,
sinon toutes les pages (connexion comprise) tournent en boucle de redirection.
"""
import os
import sys
from pathlib import Path
from urllib.parse import unquote_to_bytes

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.wsgi import application as django_app  # noqa: E402

PATH_PARAM = "__path"


def app(environ, start_response):
    kept, original = [], None
    for part in environ.get("QUERY_STRING", "").split("&"):
        name, _, value = part.partition("=")
        if name == PATH_PARAM:
            original = value
        elif part:
            kept.append(part)
    if original is not None:
        path = unquote_to_bytes(original.replace("+", "%20")).decode("latin-1")  # PEP 3333 : octets en latin-1
        environ["PATH_INFO"] = path if path.startswith("/") else "/" + path
        environ["SCRIPT_NAME"] = ""
        environ["QUERY_STRING"] = "&".join(kept)
    return django_app(environ, start_response)
