"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
from urllib.parse import unquote_to_bytes

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

if os.environ.get("VERCEL"):
    # vercel.json réécrit toutes les adresses vers /api/index?__path=/<chemin d'origine> : la fonction
    # reçoit /api/index comme chemin. On remet le chemin d'origine avant Django, sinon toutes les pages
    # (connexion comprise) tournent en boucle de redirection.
    _django = application

    def application(environ, start_response):
        kept, original = [], None
        for part in environ.get("QUERY_STRING", "").split("&"):
            name, _, value = part.partition("=")
            if name == "__path":
                original = value
            elif part:
                kept.append(part)
        if original is not None:
            path = unquote_to_bytes(original.replace("+", "%20")).decode("latin-1")  # PEP 3333 : octets en latin-1
            environ["PATH_INFO"] = path if path.startswith("/") else "/" + path
            environ["SCRIPT_NAME"] = ""
            environ["QUERY_STRING"] = "&".join(kept)
        return _django(environ, start_response)
