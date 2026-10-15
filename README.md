# FSU Caisse

Application web de gestion de caisse pour le centre de santé **FSU COM Kottiakoffikro**. Elle remplace le
fichier Excel « TABLEAU DE BORD RECETTES FSU » (une feuille par mois).

- **Journée de caisse** : saisie du *nombre* d'actes, au tarif en vigueur à la date du jour (tarifs datés),
  ventes pharmacie, dépenses par catégorie avec photo du reçu, clôture avec comptage de la caisse,
  validation par le superviseur, réouverture tracée.
- **Deux caisses** : *Entrées + Labo* et *Pharmacie + Écho*. Les commissions laboratoire sont configurables :
  15 % prescripteurs et 60 % partenaire sont reversés, 25 % ONG AIP reste en caisse.
- **Versements bancaires** avec bordereau, rapprochement mensuel et argent théorique en caisse.
- **Pharmacie** : produits, commandes, réceptions, ventes reliées au stock, inventaires, pertes et alertes de seuil.
- **Rapports** mensuel et annuel (écran, impression, export Excel), tableau de bord avec alertes.
- **Rôles** : Caissier, Superviseur, Pharmacie, Consultation et administrateur, avec **journal d'activité** complet.
- **Import** de l'ancien Excel, avec correction des dates et contrôle des totaux.

Pile technique : Django 5.2 LTS, HTMX (fourni en local), SQLite en mode WAL (PostgreSQL possible) et Waitress.
L'application n'a aucune dépendance Internet : elle fonctionne entièrement sur le réseau local.

## Règle de calcul (colonne AJ de l'Excel)

```
Net Entrées+Labo   = actes de la caisse Entrées (labo compris) − commissions reversées − dépenses de cette caisse
Net Pharma+Écho    = échographies + ventes pharmacie − dépenses de cette caisse
Recette nette      = Net Entrées+Labo + Net Pharma+Écho
Argent en caisse   = argent au démarrage + Σ recettes nettes − Σ versements
```

L'ancien tableau avait une seconde colonne, AG, qui soustrayait l'échographie nette comme une dépense.
Elle n'est pas reprise. L'import de 2026 retrouve la colonne AJ **au franc près pour chaque mois** (janvier à octobre).

## Développement

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DEBUG=1
python manage.py migrate
python manage.py init_fsu --nom "FSU COM KOTTIAKOFFIKRO" --demarrage 2026-01-01
python manage.py createsuperuser
python manage.py import_excel TABLEAU_DE_BORD_RECETTES_FSU_2026.xlsx --annee 2026 --produits   # facultatif
python manage.py runserver 0.0.0.0:8000
python manage.py test
```

## Commandes utiles

| Commande | Rôle |
|---|---|
| `init_fsu` | Rôles, actes et tarifs, commissions, catégories de dépenses, banques (relançable) |
| `import_excel <fichier> --annee 2026 [--essai] [--remplacer] [--produits]` | Import de l'ancien tableau |
| `sauvegarder` | Zip base + justificatifs → `data/sauvegardes` (+ copie `BACKUP_COPY_DIR`) |
| `restaurer <zip>` | Restauration (serveur arrêté) |
| `python serve.py` | Serveur de production (Waitress, port `PORT`, 80 par défaut) |

## Structure

```
config/        réglages (lecture du fichier .env), URLs
core/          établissement, rôles, journal d'activité, tableau de bord, sauvegardes
caisse/        actes, tarifs, commissions, journées, dépenses, versements ; services.py = calculs
stock/         produits, commandes, mouvements de stock (ventes synchronisées par signal)
rapports/      rapports mensuel/annuel et exports Excel
templates/     gabarits HTML (français)
static/        CSS et htmx.min.js (local)
deploiement/   kit Windows (installer.bat/.ps1, mise à jour, désinstallation, wheels hors ligne) et guides
```

Déploiement : voir [`deploiement/GUIDE-INSTALLATION.md`](deploiement/GUIDE-INSTALLATION.md).
