#!/usr/bin/env bash
# Mise à jour de CSU Caisse sur le serveur Ubuntu : sauvegarde, nouvelle version (git), dépendances,
# base de données, redémarrage.
#
#   sudo bash /opt/csu-caisse/deploiement/ubuntu/mettre-a-jour.sh
set -euo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UTILISATEUR=csu
VENV_PY="$APP/.venv/bin/python"
SERVICE=csu-caisse

etape() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok() { printf '    \033[32m%s\033[0m\n' "$1"; }
erreur() { printf '\033[31m%s\033[0m\n' "$1" >&2; exit 1; }
manage() { (cd "$APP" && runuser -u "$UTILISATEUR" -- "$VENV_PY" manage.py "$@"); }

[ "$(id -u)" -eq 0 ] || erreur "Lancez ce script avec sudo."
[ -x "$VENV_PY" ] || erreur "Application non installée : lancez d'abord deploiement/ubuntu/installer.sh"
cd "$APP"

etape "Sauvegarde avant mise à jour"
manage sauvegarder || erreur "Sauvegarde impossible : mise à jour annulée."

etape "Nouvelle version"
if [ -d .git ]; then
  avant="$(git rev-parse --short HEAD)"
  git pull --ff-only || erreur "git pull impossible (fichiers modifiés sur le serveur ?). Voir : git status"
  ok "Version $avant -> $(git rev-parse --short HEAD)"
else
  ok "Pas de dépôt git : nouveaux fichiers supposés déjà copiés dans $APP (sans toucher à .env)"
fi

etape "Dépendances"
"$VENV_PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt

etape "Base de données"
systemctl stop "$SERVICE"
if ! manage migrate --noinput; then
  systemctl start "$SERVICE"
  erreur "Migration impossible. Si besoin, restaurez la sauvegarde créée ci-dessus (voir GUIDE-VPS.md § 6)."
fi
manage collectstatic --noinput -v 0
manage init_fsu -v 0

etape "Redémarrage du serveur"
systemctl start "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" || erreur "Le serveur ne démarre pas. Voir : journalctl -u $SERVICE -n 50"
printf '\033[32mMise à jour terminée.\033[0m\n'
