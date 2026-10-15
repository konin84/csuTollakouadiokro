"""Restaure une sauvegarde créée par `sauvegarder`.

    python manage.py restaurer C:\\FSUCaisse\\data\\sauvegardes\\fsu-caisse_2026-10-15_2000.zip

ARRÊTEZ LE SERVEUR AVANT (tâche planifiée « FSU Caisse - Serveur »).
La base actuelle est d'abord mise de côté (fichier .avant-restauration).
"""
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Restaure une sauvegarde (base + justificatifs). Le serveur doit être arrêté."

    def add_arguments(self, parser):
        parser.add_argument("fichier")
        parser.add_argument("--oui", action="store_true", help="Ne pas demander de confirmation")

    def handle(self, *args, **opts):
        path = Path(opts["fichier"])
        if not path.exists():
            raise CommandError(f"Fichier introuvable : {path}")
        if not opts["oui"]:
            answer = input("Les données actuelles seront remplacées. Taper OUI pour continuer : ")
            if answer.strip().upper() != "OUI":
                raise CommandError("Restauration annulée.")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if connection.vendor == "sqlite":
                if "fsu_caisse.sqlite3" not in names:
                    raise CommandError("Cette sauvegarde ne contient pas de base SQLite.")
                db = Path(settings.DATABASES["default"]["NAME"])
                connection.close()
                if db.exists():
                    shutil.move(db, db.with_name(db.name + f".avant-restauration-{stamp}"))
                for suffix in ("-wal", "-shm"):
                    Path(str(db) + suffix).unlink(missing_ok=True)
                with z.open("fsu_caisse.sqlite3") as src, open(db, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            else:
                if "donnees.json" not in names:
                    raise CommandError("Cette sauvegarde ne contient pas d'export JSON.")
                tmp = Path(settings.DATA_DIR) / f"restauration-{stamp}.json"
                tmp.write_bytes(z.read("donnees.json"))
                call_command("flush", "--no-input")
                call_command("loaddata", str(tmp))
                tmp.unlink()
            media = Path(settings.MEDIA_ROOT)
            files = [n for n in names if n.startswith("justificatifs/") and not n.endswith("/")]
            if files:
                if media.exists():
                    shutil.move(media, media.with_name(media.name + f".avant-restauration-{stamp}"))
                for n in files:
                    out = media / Path(n).relative_to("justificatifs")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(n) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        call_command("migrate", verbosity=0)
        self.stdout.write(self.style.SUCCESS("Restauration terminée. Vous pouvez redémarrer le serveur."))
