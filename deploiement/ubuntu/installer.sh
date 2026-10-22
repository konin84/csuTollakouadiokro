#!/usr/bin/env bash
# Installation de CSU Caisse sur un serveur Ubuntu (VPS) : Waitress derrière Caddy (HTTPS automatique).
#
#   sudo git clone https://github.com/konin84/csuTollakouadiokro.git /opt/csu-caisse
#   sudo bash /opt/csu-caisse/deploiement/ubuntu/installer.sh --domaine caisse.exemple.ci --email vous@exemple.ci
#
# Le script peut être relancé : il ne recrée que ce qui manque et ne supprime aucune donnée.
# Guide complet : deploiement/GUIDE-VPS.md
set -euo pipefail

NOM="Centre de Santé Urbain (CSU) de KOTIAKOFFIKRO"
DOMAINE=""
EMAIL=""
BASE=""
ANNEE="$(date +%Y)"
EXCEL=""
COPIE=""
HEURE="20:00"
PORT=8000

usage() {
  cat <<'EOF'
Usage : sudo bash deploiement/ubuntu/installer.sh [options]

  --domaine NOM            nom de domaine du site (ex. caisse.exemple.ci) : HTTPS automatique.
                           Sans domaine : site en HTTP simple sur l'adresse IP du serveur.
  --email ADRESSE          adresse prévenue par Let's Encrypt si le certificat pose problème
  --base-de-donnees URL    PostgreSQL existant (ex. Neon) au lieu de SQLite sur le serveur
  --nom "NOM"              nom de l'établissement (première installation)
  --annee AAAA             année de démarrage des tarifs (première installation)
  --excel FICHIER          importer l'ancien tableau Excel de cette année
  --copie-sauvegarde DOSSIER  copie supplémentaire de chaque sauvegarde (disque monté…)
  --heure-sauvegarde HH:MM sauvegarde quotidienne (20:00 par défaut)
  --port N                 port interne de Waitress (8000 par défaut)

Variables facultatives (installation sans questions) :
  SUPERVISEUR_MOT_DE_PASSE, DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_PASSWORD
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --domaine) DOMAINE="$2"; shift 2 ;;
    --email) EMAIL="$2"; shift 2 ;;
    --base-de-donnees) BASE="$2"; shift 2 ;;
    --nom) NOM="$2"; shift 2 ;;
    --annee) ANNEE="$2"; shift 2 ;;
    --excel) EXCEL="$2"; shift 2 ;;
    --copie-sauvegarde) COPIE="$2"; shift 2 ;;
    --heure-sauvegarde) HEURE="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    *) echo "Option inconnue : $1" >&2; usage; exit 1 ;;
  esac
done

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA=/var/lib/csu-caisse
UTILISATEUR=csu
VENV_PY="$APP/.venv/bin/python"
ENV_FILE="$APP/.env"
SERVICE=csu-caisse

etape() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok() { printf '    \033[32m%s\033[0m\n' "$1"; }
attention() { printf '    \033[33m%s\033[0m\n' "$1"; }
erreur() { printf '\033[31m%s\033[0m\n' "$1" >&2; exit 1; }
# Commandes Django sous l'utilisateur du service : les fichiers créés (base, journaux) lui appartiennent.
manage() { (cd "$APP" && runuser -u "$UTILISATEUR" -- "$VENV_PY" manage.py "$@"); }
compter() { manage shell --no-imports -c "$1" 2>/dev/null | tail -n 1; }
# .env : env_defaut n'écrit que si la clé manque (relance sans risque), env_fixer remplace la valeur.
env_defaut() { grep -q "^$1=" "$ENV_FILE" 2>/dev/null || printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"; }
env_fixer() {
  grep -v "^$1=" "$ENV_FILE" > "$ENV_FILE.tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE.tmp"
  mv "$ENV_FILE.tmp" "$ENV_FILE"
}
env_lire() { grep "^$1=" "$ENV_FILE" 2>/dev/null | tail -n 1 | cut -d= -f2- || true; }

[ "$(id -u)" -eq 0 ] || erreur "Lancez ce script avec sudo."
# shellcheck disable=SC1091
. /etc/os-release
[ "${ID:-}" = ubuntu ] || attention "Système détecté : ${PRETTY_NAME:-inconnu}. Ce script est prévu pour Ubuntu."
[[ "$HEURE" =~ ^[0-2][0-9]:[0-5][0-9]$ ]] || erreur "--heure-sauvegarde : format HH:MM attendu."
echo "Installation de CSU Caisse dans $APP (données : $DATA)"

# 1. Paquets système ------------------------------------------------------------
etape "Paquets système (Python, Caddy, pare-feu)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl ufw ca-certificates gnupg >/dev/null
if ! command -v caddy >/dev/null; then
  if ! apt-get install -y -qq caddy >/dev/null 2>&1; then
    # dépôt officiel de Caddy si le paquet Ubuntu n'est pas disponible
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key |
      gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
    apt-get install -y -qq caddy >/dev/null
  fi
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || erreur "Python 3.10 ou plus récent est nécessaire."
timedatectl set-timezone Africa/Abidjan 2>/dev/null || true  # heure des sauvegardes = heure locale
ok "Python $(python3 -c 'import platform; print(platform.python_version())'), $(caddy version | cut -d' ' -f1)"

# 2. Utilisateur et dossiers ------------------------------------------------------
etape "Utilisateur « $UTILISATEUR » et dossier des données"
id -u "$UTILISATEUR" >/dev/null 2>&1 ||
  useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin "$UTILISATEUR"
install -d -o "$UTILISATEUR" -g "$UTILISATEUR" -m 750 "$DATA"
install -d -o "$UTILISATEUR" -g "$UTILISATEUR" "$APP/staticfiles"
ok "Données dans $DATA (base, justificatifs, sauvegardes, journaux)"

# 3. Environnement Python ------------------------------------------------------------
etape "Environnement Python et dépendances"
[ -x "$VENV_PY" ] || python3 -m venv "$APP/.venv"
"$VENV_PY" -m pip install --quiet --disable-pip-version-check --upgrade pip
"$VENV_PY" -m pip install --quiet --disable-pip-version-check -r "$APP/requirements.txt"
ok "Dépendances installées"

# 4. Configuration (.env) ------------------------------------------------------------
etape "Configuration"
if [ -f "$ENV_FILE" ]; then ok "Fichier .env existant conservé (seules les valeurs manquantes sont ajoutées)"; fi
touch "$ENV_FILE"
env_defaut SECRET_KEY "$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
env_defaut DEBUG 0
env_defaut HOST 127.0.0.1
env_defaut PORT "$PORT"
env_defaut TRUSTED_PROXY 127.0.0.1
env_defaut DATA_DIR "$DATA"
env_defaut BACKUP_KEEP_DAYS 30
if [ -n "$DOMAINE" ]; then  # domaine donné (ou changé) : on met à jour les réglages qui en dépendent
  env_fixer ALLOWED_HOSTS "$DOMAINE"
  env_fixer CSRF_TRUSTED_ORIGINS "https://$DOMAINE"
  env_fixer HTTPS 1
else
  env_defaut ALLOWED_HOSTS "*"
  env_defaut HTTPS 0
  hotes="$(env_lire ALLOWED_HOSTS)"
  if [ "$hotes" != "*" ]; then DOMAINE="$hotes"; fi  # relance sans --domaine : on garde celui déjà configuré
fi
if [ -n "$BASE" ]; then env_fixer DATABASE_URL "$BASE"; fi
if [ -n "$COPIE" ]; then env_fixer BACKUP_COPY_DIR "$COPIE"; fi
COPIE="$(env_lire BACKUP_COPY_DIR)"
PORT="$(env_lire PORT)"
chown root:"$UTILISATEUR" "$ENV_FILE"
chmod 640 "$ENV_FILE"  # clé secrète et mot de passe de la base : lisibles par le service seulement
if [ -n "$COPIE" ]; then install -d -o "$UTILISATEUR" -g "$UTILISATEUR" -m 750 "$COPIE"; fi
ok "Fichier $ENV_FILE prêt"

# 5. Base de données --------------------------------------------------------------------
etape "Base de données"
manage migrate --noinput -v 0
manage collectstatic --noinput -v 0
if [ "$(compter "from django.contrib.auth.models import User; print(User.objects.filter(groups__name='Superviseur').count())")" = 0 ] &&
  [ -z "${SUPERVISEUR_MOT_DE_PASSE:-}" ]; then
  etape "Mot de passe du compte superviseur « konin »"
  while true; do
    read -rsp "    Mot de passe (6 caractères minimum) : " mdp; echo
    [ "${#mdp}" -ge 6 ] || { attention "Trop court."; continue; }
    read -rsp "    Confirmer le mot de passe : " mdp2; echo
    [ "$mdp" = "$mdp2" ] && break
    attention "Les deux saisies diffèrent."
  done
  export SUPERVISEUR_MOT_DE_PASSE="$mdp"
  unset mdp mdp2
fi
manage init_fsu --nom "$NOM" --demarrage "$ANNEE-01-01"
unset SUPERVISEUR_MOT_DE_PASSE

if [ "$(compter "from django.contrib.auth.models import User; print(User.objects.filter(is_superuser=True).count())")" = 0 ]; then
  etape "Compte administrateur (gère les paramètres et les utilisateurs)"
  if [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    export DJANGO_SUPERUSER_USERNAME="${DJANGO_SUPERUSER_USERNAME:-admin}" DJANGO_SUPERUSER_EMAIL="${DJANGO_SUPERUSER_EMAIL:-}"
    manage createsuperuser --no-input
    ok "Administrateur créé : « $DJANGO_SUPERUSER_USERNAME »"
  else
    manage createsuperuser
  fi
fi

if [ -n "$EXCEL" ]; then
  etape "Import de l'ancien tableau Excel ($ANNEE)"
  install -o "$UTILISATEUR" -m 600 "$EXCEL" "$DATA/import-excel.xlsx"
  manage import_excel "$DATA/import-excel.xlsx" --annee "$ANNEE" --produits
  rm -f "$DATA/import-excel.xlsx"
fi

# 6. Services systemd --------------------------------------------------------------------
etape "Démarrage automatique du serveur et sauvegarde quotidienne"
ECRITURE="$DATA${COPIE:+ $COPIE}"
cat > "/etc/systemd/system/$SERVICE.service" <<EOF
# Généré par deploiement/ubuntu/installer.sh
[Unit]
Description=CSU Caisse (serveur web Waitress)
After=network-online.target
Wants=network-online.target

[Service]
User=$UTILISATEUR
Group=$UTILISATEUR
WorkingDirectory=$APP
ExecStart=$VENV_PY $APP/serve.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA

[Install]
WantedBy=multi-user.target
EOF
cat > "/etc/systemd/system/$SERVICE-sauvegarde.service" <<EOF
# Généré par deploiement/ubuntu/installer.sh
[Unit]
Description=CSU Caisse : sauvegarde (base + justificatifs)

[Service]
Type=oneshot
User=$UTILISATEUR
Group=$UTILISATEUR
WorkingDirectory=$APP
ExecStart=$VENV_PY $APP/manage.py sauvegarder
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$ECRITURE
EOF
cat > "/etc/systemd/system/$SERVICE-sauvegarde.timer" <<EOF
# Généré par deploiement/ubuntu/installer.sh
[Unit]
Description=CSU Caisse : sauvegarde quotidienne à $HEURE

[Timer]
OnCalendar=*-*-* $HEURE:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now "$SERVICE-sauvegarde.timer" >/dev/null 2>&1
systemctl enable "$SERVICE" >/dev/null 2>&1
systemctl restart "$SERVICE"
ok "Service « $SERVICE » : démarre avec le serveur"
ok "Sauvegarde : tous les jours à $HEURE dans $DATA/sauvegardes${COPIE:+ (+ copie dans $COPIE)}"

# 7. Caddy (HTTPS) ------------------------------------------------------------------------
sans_domaine="HTTP sur l'adresse IP (pas de domaine)"
etape "Caddy : ${DOMAINE:-$sans_domaine}"
CADDYFILE=/etc/caddy/Caddyfile
if [ -f "$CADDYFILE" ] && ! grep -q "CSU Caisse" "$CADDYFILE"; then
  cp "$CADDYFILE" "$CADDYFILE.avant-csu-caisse"
  attention "Ancien Caddyfile mis de côté : $CADDYFILE.avant-csu-caisse"
fi
{
  echo "# CSU Caisse : généré par deploiement/ubuntu/installer.sh"
  if [ -n "$EMAIL" ]; then printf '{\n\temail %s\n}\n\n' "$EMAIL"; fi
  echo "${DOMAINE:-:80} {"
  printf '\tencode zstd gzip\n'
  printf '\trequest_body {\n\t\tmax_size 25MB\n\t}\n'
  printf '\treverse_proxy 127.0.0.1:%s\n' "$PORT"
  echo "}"
} > "$CADDYFILE"
caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1 || erreur "Caddyfile invalide : caddy validate --config $CADDYFILE"
systemctl enable caddy >/dev/null 2>&1
systemctl restart caddy
ok "Caddy configuré ($CADDYFILE)"

# 8. Pare-feu -------------------------------------------------------------------------------
etape "Pare-feu : SSH, HTTP et HTTPS uniquement"
ufw allow OpenSSH >/dev/null
# port SSH personnalisé : on l'ouvre aussi, pour ne pas perdre l'accès au serveur
for p in $( (sshd -T 2>/dev/null | awk '$1 == "port" {print $2}'
             ss -tlnpH 2>/dev/null | awk '/sshd/ {n = split($4, a, ":"); print a[n]}') | sort -u); do
  ufw allow "$p/tcp" >/dev/null
done
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ok "Pare-feu actif ($(ufw status | grep -c ALLOW) règles)"

# 9. Vérification -----------------------------------------------------------------------------
etape "Vérification"
code=000
for _ in $(seq 1 20); do
  code="$(curl -s -o /dev/null -w '%{http_code}' -H "Host: ${DOMAINE:-localhost}" "http://127.0.0.1:$PORT/connexion/" || true)"
  [ "$code" = 200 ] && break
  sleep 1
done
[ "$code" = 200 ] || erreur "Le serveur ne répond pas (code $code). Voir : journalctl -u $SERVICE -n 50"
ok "L'application répond."

IP="$(curl -s -4 -m 5 https://api.ipify.org || hostname -I | awk '{print $1}')"
echo
printf '\033[32mInstallation terminée.\033[0m\n'
if [ -n "$DOMAINE" ]; then
  echo "Adresse : https://$DOMAINE"
  attention "Le domaine doit pointer vers ce serveur (enregistrement DNS A : $DOMAINE -> $IP)."
  attention "Le certificat HTTPS est obtenu automatiquement à la première visite (quelques secondes)."
else
  echo "Adresse : http://$IP"
  attention "Sans domaine, le site est en HTTP (non chiffré). Dès que possible : relancer avec --domaine."
fi
echo "Ensuite : connectez-vous en administrateur et ouvrez Paramètres pour créer les comptes et vérifier les tarifs."
