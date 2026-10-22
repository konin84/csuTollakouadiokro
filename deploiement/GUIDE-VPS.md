# CSU Caisse – Guide d'installation sur un serveur Ubuntu (VPS)

L'application tourne sur **un serveur loué sur Internet** (VPS). Elle s'ouvre depuis n'importe quel
ordinateur, tablette ou téléphone connecté à Internet, à une adresse du type `https://caisse.exemple.ci`.

| Élément | Rôle |
|---|---|
| **Waitress** (`serve.py`) | Serveur de l'application, service système `csu-caisse`, démarre avec le serveur |
| **Caddy** | Reçoit les visiteurs, gère le **HTTPS** (certificat Let's Encrypt gratuit, renouvelé seul) |
| **SQLite** | Base de données : un seul fichier, dans `/var/lib/csu-caisse` (PostgreSQL / Neon possible) |
| **Sauvegarde** | Tous les jours à 20 h (minuterie système `csu-caisse-sauvegarde.timer`) |
| **Pare-feu (ufw)** | Seuls SSH, HTTP (80) et HTTPS (443) sont ouverts |

---

## 1. Ce qu'il faut

| Élément | Recommandation |
|---|---|
| VPS | **Ubuntu 24.04 LTS** (22.04 convient aussi), 1 processeur, **1 à 2 Go de RAM**, 20 Go de disque |
| Accès | L'adresse IP du serveur et le mot de passe (ou la clé SSH) du compte `root` ou d'un compte `sudo` |
| Nom de domaine | Conseillé (ex. `caisse.csu-kotiakoffikro.ci`) : indispensable pour le HTTPS |
| Sauvegarde hors serveur | Un PC du centre (ou un disque) où rapatrier les sauvegardes chaque semaine |

---

## 2. Nom de domaine (avant l'installation)

Chez le fournisseur du domaine, dans la **zone DNS**, créer un enregistrement :

| Type | Nom | Valeur |
|---|---|---|
| `A` | `caisse` (ou `@` pour le domaine principal) | l'adresse IP du VPS |

La prise en compte prend de quelques minutes à quelques heures. Vérifier depuis un PC :
`ping caisse.exemple.ci` doit afficher l'adresse IP du VPS.

---

## 3. Installation

Se connecter au serveur depuis un PC (PowerShell sous Windows) :

```bash
ssh root@ADRESSE_IP_DU_VPS
```

Puis, sur le serveur :

```bash
apt-get update && apt-get install -y git
git clone https://github.com/konin84/csuTollakouadiokro.git /opt/csu-caisse
bash /opt/csu-caisse/deploiement/ubuntu/installer.sh --domaine caisse.exemple.ci --email vous@exemple.ci
```

(Avec un compte `sudo` plutôt que `root` : ajouter `sudo` devant chaque commande.)

Le script :
- installe Python, Caddy et le pare-feu ;
- crée l'utilisateur système `csu` (le serveur ne tourne jamais en `root`) et le dossier des données
  `/var/lib/csu-caisse` ;
- génère la configuration `/opt/csu-caisse/.env` (clé secrète, domaine…) ;
- demande le **mot de passe du compte superviseur `konin`**, puis de **créer le compte administrateur**
  (identifiant + mot de passe : à noter et à garder en lieu sûr) ;
- programme le démarrage automatique et la **sauvegarde chaque soir à 20 h** ;
- configure Caddy (HTTPS) et le pare-feu, puis vérifie que l'application répond.

Ouvrir ensuite `https://caisse.exemple.ci` : le certificat HTTPS est obtenu à la première visite.

### Options

| Option | Effet |
|---|---|
| `--domaine NOM` | Site en HTTPS sur ce domaine. **Sans domaine** : site en HTTP simple sur `http://ADRESSE_IP` (non chiffré : à réserver aux essais) |
| `--email ADRESSE` | Adresse prévenue par Let's Encrypt en cas de problème de certificat |
| `--base-de-donnees URL` | Utiliser un PostgreSQL existant (ex. Neon) au lieu de SQLite |
| `--excel FICHIER --annee 2026` | Reprendre l'historique de l'ancien fichier Excel (copier d'abord le fichier sur le serveur, voir § 6) |
| `--copie-sauvegarde DOSSIER` | Copier aussi chaque sauvegarde dans ce dossier (disque supplémentaire monté sur le serveur) |
| `--heure-sauvegarde 21:30` | Changer l'heure de la sauvegarde quotidienne |

Le script peut être relancé sans risque : il ne supprime aucune donnée et ne redemande pas les mots de passe.
Pour **ajouter un domaine plus tard** : relancer le script avec `--domaine`.

---

## 4. Premiers réglages

Se connecter avec le compte administrateur, puis suivre le § 4 « Premiers réglages » de
[GUIDE-INSTALLATION.md](GUIDE-INSTALLATION.md) (établissement, tarifs, commissions, banques, utilisateurs, pharmacie).

---

## 5. Reprendre les données de Render / Neon

À faire **une seule fois**, juste après l'installation, si le centre travaillait déjà sur Render (base Neon).
Prévenir les utilisateurs : ce qui sera saisi sur Render après l'étape 1 ne sera pas repris.

1. Exporter la base Neon (URL **directe**, sans `-pooler`, depuis Neon → Connect) :
   ```bash
   cd /opt/csu-caisse
   sudo -u csu env DATABASE_URL='postgresql://…neon.tech/neondb?sslmode=require' .venv/bin/python manage.py sauvegarder
   ```
   Le fichier créé s'affiche : `/var/lib/csu-caisse/sauvegardes/fsu-caisse_AAAA-MM-JJ_HHMM.zip`.
2. Le charger dans la base du VPS (elle est entièrement remplacée) :
   ```bash
   systemctl stop csu-caisse
   sudo -u csu .venv/bin/python manage.py restaurer /var/lib/csu-caisse/sauvegardes/fsu-caisse_AAAA-MM-JJ_HHMM.zip
   systemctl start csu-caisse
   ```
3. Se connecter sur le VPS avec les comptes habituels et vérifier les dernières journées.
4. Ne plus utiliser Render (le supprimer, ou le garder arrêté quelques semaines par précaution).

Les photos des justificatifs ne sont pas reprises : Render ne les conservait pas.

---

## 6. Sauvegardes

- Chaque soir à 20 h : sauvegarde complète (base + justificatifs) dans `/var/lib/csu-caisse/sauvegardes`.
  Les sauvegardes de plus de 30 jours sont effacées automatiquement.
- **Sauvegarde immédiate** : `systemctl start csu-caisse-sauvegarde`
- Voir les sauvegardes : `ls -lh /var/lib/csu-caisse/sauvegardes`

### Copier les sauvegardes hors du serveur (au moins une fois par semaine)

Si le serveur ou le compte chez l'hébergeur est perdu, seule cette copie restera. Depuis un PC Windows du
centre (PowerShell), avec une clé USB en `E:` :

```powershell
mkdir E:\SauvegardesCSU -Force
scp "root@ADRESSE_IP_DU_VPS:/var/lib/csu-caisse/sauvegardes/*.zip" E:\SauvegardesCSU\
```

Envoyer un fichier vers le serveur (ex. l'Excel à importer) : `scp C:\chemin\fichier.xlsx root@ADRESSE_IP_DU_VPS:/root/`

### Restaurer une sauvegarde

```bash
systemctl stop csu-caisse
cd /opt/csu-caisse
sudo -u csu .venv/bin/python manage.py restaurer /var/lib/csu-caisse/sauvegardes/fsu-caisse_2026-10-15_2000.zip
systemctl start csu-caisse
```

La base remplacée est conservée à côté (fichier `.avant-restauration-…`).

---

## 7. Mise à jour de l'application

```bash
bash /opt/csu-caisse/deploiement/ubuntu/mettre-a-jour.sh
```

Le script fait une sauvegarde, récupère la nouvelle version (`git pull`), met à jour les dépendances et la base,
puis redémarre le serveur (coupure de quelques secondes : à faire hors des heures d'affluence).

---

## 8. Commandes utiles et problèmes

| Besoin | Commande |
|---|---|
| État du serveur | `systemctl status csu-caisse` |
| Redémarrer le serveur | `systemctl restart csu-caisse` |
| Journal du serveur (erreurs) | `journalctl -u csu-caisse -n 100` et `/var/lib/csu-caisse/fsu_caisse.log` |
| Journal de Caddy (HTTPS, certificat) | `journalctl -u caddy -n 100` |
| Prochaine sauvegarde | `systemctl list-timers csu-caisse-sauvegarde.timer` |
| Mot de passe administrateur oublié | `cd /opt/csu-caisse && sudo -u csu .venv/bin/python manage.py changepassword admin` |
| Modifier la configuration | `nano /opt/csu-caisse/.env`, puis `systemctl restart csu-caisse` |

| Symptôme | À vérifier |
|---|---|
| Le site ne s'ouvre pas | Le domaine pointe-t-il vers l'IP du VPS (§ 2) ? `systemctl status caddy csu-caisse` |
| Avertissement de certificat | DNS pas encore propagé : patienter, puis `systemctl restart caddy` ; voir `journalctl -u caddy` |
| « Bad Request (400) » | Le site est ouvert avec une autre adresse que le domaine configuré : relancer l'installateur avec `--domaine` |
| « Interdit (403) – vérification CSRF » | Fermer l'onglet et rouvrir l'adresse ; vérifier `CSRF_TRUSTED_ORIGINS` dans `.env` |

---

## 9. Sécurité

- Les mises à jour de sécurité d'Ubuntu s'installent automatiquement (`unattended-upgrades`, actif par défaut).
  Redémarrer le VPS de temps en temps : `reboot` (le serveur et Caddy repartent seuls).
- Préférer une **clé SSH** au mot de passe `root`, et un mot de passe long pour chaque compte de l'application.
- Le fichier `.env` contient la clé secrète : ne jamais le copier dans un e-mail ou sur GitHub.
- L'application contient des **noms de patients** : seules les personnes autorisées doivent avoir un compte ;
  désactiver le compte d'une personne qui quitte le centre (Paramètres → Utilisateurs).
