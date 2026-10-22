#!/usr/bin/env bash
# Build Render : dépendances, fichiers statiques, migrations et données de départ.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py init_fsu
