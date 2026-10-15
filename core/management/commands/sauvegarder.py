"""Sauvegarde complète : base de données + justificatifs, dans un seul fichier .zip.

    python manage.py sauvegarder

- SQLite : copie « à chaud » cohérente (API de sauvegarde SQLite), même si des postes travaillent.
- PostgreSQL : export JSON (dumpdata) de toutes les données.
- Le fichier est écrit dans BACKUP_DIR (data\\sauvegardes) puis copié dans BACKUP_COPY_DIR
  (clé USB, disque externe, dossier synchronisé…) si ce dossier est défini et accessible.
- Les sauvegardes de plus de BACKUP_KEEP_DAYS jours sont supprimées.
"""
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Sauvegarde la base de données et les justificatifs dans un fichier zip."

    def handle(self, *args, **opts):
        backup_dir = Path(settings.BACKUP_DIR)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        target = backup_dir / f"fsu-caisse_{stamp}.zip"

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as z:
                if connection.vendor == "sqlite":
                    db_copy = tmp / "fsu_caisse.sqlite3"
                    src = sqlite3.connect(str(settings.DATABASES["default"]["NAME"]))
                    dst = sqlite3.connect(str(db_copy))
                    with dst:
                        src.backup(dst)
                    dst.close()
                    src.close()
                    z.write(db_copy, "fsu_caisse.sqlite3")
                else:
                    out = StringIO()
                    call_command("dumpdata", "--natural-foreign", "--exclude", "contenttypes",
                                 "--exclude", "auth.permission", "--exclude", "sessions", stdout=out)
                    z.writestr("donnees.json", out.getvalue())
                media = Path(settings.MEDIA_ROOT)
                if media.exists():
                    for f in media.rglob("*"):
                        if f.is_file():
                            z.write(f, Path("justificatifs") / f.relative_to(media))
                z.writestr("LISEZMOI.txt",
                           "Sauvegarde FSU Caisse du " + datetime.now().strftime("%d/%m/%Y %H:%M") + "\n"
                           "Restauration : python manage.py restaurer <ce fichier.zip> (serveur arrêté)\n")

        size = target.stat().st_size / 1024
        self.stdout.write(self.style.SUCCESS(f"Sauvegarde créée : {target} ({size:.0f} Ko)"))

        copy_dir = settings.BACKUP_COPY_DIR
        if copy_dir:
            dest = Path(copy_dir)
            try:
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, dest / target.name)
                self.stdout.write(f"Copie : {dest / target.name}")
                self._prune(dest)
            except OSError as exc:
                self.stderr.write(f"Copie impossible vers {dest} : {exc} (clé USB / disque branché ?)")
        self._prune(backup_dir)

    def _prune(self, folder: Path):
        limit = time.time() - settings.BACKUP_KEEP_DAYS * 86400
        for f in folder.glob("fsu-caisse_*.zip"):
            if f.stat().st_mtime < limit:
                f.unlink(missing_ok=True)
