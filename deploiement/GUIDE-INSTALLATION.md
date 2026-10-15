# FSU Caisse – Guide d'installation sur le réseau local (Windows)

L'application tourne sur **un PC Windows du centre** (le « serveur »). Les autres postes,
tablettes et téléphones connectés au même réseau (câble ou Wi-Fi) l'ouvrent simplement dans
leur navigateur. **Aucune connexion Internet n'est nécessaire** au fonctionnement.

---

## 1. Matériel conseillé

| Élément | Recommandation |
|---|---|
| PC serveur | Windows 10 ou 11 **64 bits**, 4 Go de RAM minimum, disque SSD de préférence |
| Disponibilité | Le PC reste allumé pendant les heures d'ouverture (le serveur redémarre seul avec Windows) |
| Onduleur | **Indispensable** : une coupure brutale peut endommager la base de données |
| Réseau | Box ou routeur Wi-Fi ; réserver une adresse IP fixe au PC serveur (voir § 5) |
| Sauvegarde | Une clé USB ou un disque externe dédié, toujours branché sur le serveur |

---

## 2. Installer Python (une seule fois)

1. Télécharger **Python 3.12 ou 3.13 – Windows installer (64-bit)** sur
   https://www.python.org/downloads/windows/ (à faire depuis n'importe quel PC connecté, puis copier le fichier sur clé USB).
2. Lancer l'installateur, cocher **« Add python.exe to PATH »**, cliquer **« Customize installation »**,
   puis cocher **« Install Python for all users »**, et terminer l'installation.

---

## 3. Installer FSU Caisse

1. Copier le dossier `fsu-caisse` sur le PC serveur, par exemple dans **`C:\FSUCaisse`**.
   (Les bibliothèques nécessaires sont fournies dans `deploiement\windows\wheels` : pas besoin d'Internet.)
2. Ouvrir `C:\FSUCaisse\deploiement\windows` et **double-cliquer sur `installer.bat`**.
   Accepter la demande d'autorisation administrateur.
3. Le script :
   - prépare l'environnement Python et la base de données ;
   - demande de **créer le compte administrateur** (identifiant + mot de passe : à noter et à garder en lieu sûr) ;
   - ouvre le port réseau dans le pare-feu Windows (réseau privé uniquement) ;
   - désactive la mise en veille du PC sur secteur ;
   - programme le **démarrage automatique** du serveur avec Windows et une **sauvegarde chaque soir à 20 h** ;
   - affiche l'adresse à utiliser sur les autres postes, par exemple `http://192.168.1.10`.

### Options utiles

Pour les utiliser, ouvrir **PowerShell en administrateur** dans `C:\FSUCaisse` :

```powershell
# Copier aussi chaque sauvegarde sur une clé USB (lettre E:)
.\deploiement\windows\installer.ps1 -DossierCopieSauvegarde "E:\SauvegardesFSU"

# Reprendre l'historique de l'ancien fichier Excel
.\deploiement\windows\installer.ps1 -FichierExcel "C:\Users\Caisse\Documents\TABLEAU_DE_BORD_RECETTES_FSU_2026.xlsx" -Annee 2026

# Utiliser un autre port si le port 80 est déjà pris (l'adresse devient http://192.168.1.10:8080)
.\deploiement\windows\installer.ps1 -Port 8080
```

Le script peut être relancé sans risque : il ne supprime aucune donnée.

---

## 4. Premiers réglages (compte administrateur)

Se connecter avec le compte administrateur, puis menu **Paramètres** :

1. **Établissement** : vérifier le nom, la **date de démarrage** et **l'argent en caisse au démarrage**
   (l'argent réellement présent dans la caisse le matin du premier jour d'utilisation).
2. **Actes et prestations** : vérifier chaque tarif. Pour un changement de prix, **ajouter une nouvelle ligne
   de tarif avec sa date d'application** (ne pas modifier l'ancienne : l'historique reste juste).
3. **Règles de commission laboratoire** : 15 % prescripteurs, 60 % laboratoire partenaire (reversés),
   25 % ONG AIP (conservé en caisse) sont préremplis.
4. **Comptes bancaires** : BOA et Banque Populaire sont préremplis ; ajouter AFG Bank si nécessaire.
5. **Utilisateurs** : créer un compte par personne, et lui donner un ou plusieurs **groupes (rôles)** :

| Rôle | Ce que la personne peut faire |
|---|---|
| **Caissier** | Saisir recettes, dépenses, ventes et versements ; clôturer la journée |
| **Superviseur** | Valider ou rouvrir les journées (avec motif), corriger les versements, voir le journal d'activité |
| **Pharmacie** | Gérer produits, commandes, réceptions, inventaires ; saisir les ventes |
| **Consultation** | Lecture seule : tableau de bord et rapports (COGES, district…) |

6. **Pharmacie** : compléter les prix de vente des produits, puis faire un **inventaire**
   (menu Inventaire) pour enregistrer le stock de départ.

---

## 5. Adresse fixe du serveur (recommandé)

Dans l'interface de la box ou du routeur, chercher **« Réservation DHCP »** (ou « bail statique ») et associer
une adresse fixe au PC serveur. Sinon l'adresse peut changer après un redémarrage de la box et les postes
ne trouveront plus l'application. Sur les autres postes, **ajouter l'adresse aux favoris** du navigateur.

---

## 6. Sauvegardes

- Chaque soir à 20 h, une sauvegarde complète (base + photos des justificatifs) est créée dans
  `C:\FSUCaisse\data\sauvegardes` et, si l'option a été donnée, copiée sur la clé USB.
  Les sauvegardes de plus de 30 jours sont effacées automatiquement.
- **Sauvegarde immédiate** : double-cliquer sur `deploiement\windows\sauvegarder-maintenant.bat`.
- **Une fois par semaine**, emporter une copie hors du centre (2ᵉ clé USB, ou dossier synchronisé).
  En cas de vol ou d'incendie, c'est la seule copie qui restera.

### Restaurer une sauvegarde

```powershell
schtasks /End /TN "FSU Caisse - Serveur"
cd C:\FSUCaisse
.venv\Scripts\python.exe manage.py restaurer "C:\FSUCaisse\data\sauvegardes\fsu-caisse_2026-10-15_2000.zip"
schtasks /Run /TN "FSU Caisse - Serveur"
```

La base remplacée est conservée à côté (fichier `.avant-restauration-…`).

---

## 7. Mise à jour de l'application

1. Remplacer les fichiers de `C:\FSUCaisse` par la nouvelle version **sans toucher** au dossier `data`
   ni au fichier `.env`.
2. Lancer `deploiement\windows\mettre-a-jour.ps1` en administrateur (sauvegarde automatique avant mise à jour).

---

## 8. En cas de problème

| Symptôme | À vérifier |
|---|---|
| Les postes n'arrivent pas à ouvrir l'adresse | Le PC serveur est allumé ; il est sur le même réseau ; le réseau Windows est « Privé » ; l'adresse IP n'a pas changé |
| Ça fonctionne sur le serveur mais pas ailleurs | Pare-feu : relancer `installer.bat` (il recrée la règle) |
| Page « Le serveur ne répond pas » | Double-cliquer sur `redemarrer-serveur.bat` (en administrateur) ; voir `data\serveur.log` et `data\fsu_caisse.log` |
| Mot de passe oublié (utilisateur) | L'administrateur le change dans Paramètres → Utilisateurs |
| Mot de passe administrateur oublié | Sur le serveur : `.venv\Scripts\python.exe manage.py changepassword admin` |

Désinstaller (sans perdre les données) : `deploiement\windows\desinstaller.ps1` en administrateur.

---

### Variante : PostgreSQL

Par défaut la base est un fichier SQLite (`data\fsu_caisse.sqlite3`), suffisant pour un centre de santé.
Pour utiliser PostgreSQL : installer PostgreSQL, créer une base, ajouter dans `.env`
`DATABASE_URL=postgres://utilisateur:motdepasse@localhost:5432/fsu_caisse`, installer `psycopg[binary]`
dans l'environnement, puis relancer `installer.ps1`.
