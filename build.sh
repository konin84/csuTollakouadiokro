#!/usr/bin/env bash
# Build Render : dépendances, fichiers statiques, migrations et données de départ.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py init_fsu

# Compte administrateur (l'installateur Windows le demande au clavier ; ici, variables d'environnement) :
#   DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_PASSWORD, DJANGO_SUPERUSER_EMAIL (facultatif)
# Créé seulement s'il n'existe encore aucun administrateur.
if [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  export DJANGO_SUPERUSER_USERNAME="${DJANGO_SUPERUSER_USERNAME:-admin}"
  export DJANGO_SUPERUSER_EMAIL="${DJANGO_SUPERUSER_EMAIL:-}"
  if python manage.py shell -c "import sys; from django.contrib.auth.models import User; sys.exit(0 if User.objects.filter(is_superuser=True).exists() else 1)"; then
    echo "Administrateur déjà présent : rien à créer."
  else
    python manage.py createsuperuser --no-input
    echo "Administrateur créé : identifiant « $DJANGO_SUPERUSER_USERNAME »"
  fi
else
  echo "ATTENTION : aucun administrateur créé (définissez DJANGO_SUPERUSER_PASSWORD)."
fi
