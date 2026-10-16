"""Lance le serveur de l'application sur le réseau local (Waitress, sans IIS ni Apache).

    python serve.py                  # écoute sur toutes les cartes réseau, port PORT du .env (80 par défaut)

Sous Windows, ce script est lancé au démarrage du PC par la tâche planifiée
« CSU Caisse - Serveur » créée par installer.ps1.
"""
import logging
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.chdir(BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main():
    import django
    from django.conf import settings

    django.setup()
    from waitress import serve

    from config.wsgi import application

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "80"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(settings.DATA_DIR / "serveur.log", encoding="utf-8"),
                  logging.StreamHandler()],
    )
    logging.info("CSU Caisse : démarrage sur http://%s:%s (données : %s)", host, port, settings.DATA_DIR)
    serve(application, host=host, port=port, threads=int(os.environ.get("THREADS", "8")),
          ident="CSU Caisse", max_request_body_size=20 * 1024 * 1024)


if __name__ == "__main__":
    main()
