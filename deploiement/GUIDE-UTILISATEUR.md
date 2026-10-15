# FSU Caisse – Guide d'utilisation

Ouvrir le navigateur (Chrome, Edge, Firefox) sur l'adresse donnée par l'administrateur,
par exemple `http://192.168.1.10`, puis se connecter avec son identifiant.

---

## La journée de caisse (Caissier)

1. Menu **Journée du jour** → **Ouvrir la journée du jour**.
2. **Patients du jour** : à chaque patient, cliquer **+ Nouveau patient** :
   - saisir le **nom et prénoms** (téléphone, sexe et âge si possible) ;
   - **ajouter les actes** : le prix du tarif du jour s'affiche, le montant est calculé ;
     pour le **laboratoire**, saisir le montant ;
   - **ajouter les produits** vendus : le stock restant s'affiche ; une quantité supérieure au stock est refusée ;
   - **Enregistrer** : le reçu numéroté s'affiche → **Imprimer le reçu** → **+ Patient suivant**.
   Un reçu se **modifie** tant que la journée est ouverte. En cas d'erreur, l'**annuler** avec un motif
   (il reste visible, barré, et n'est plus compté ; les produits reviennent en stock).
   Certains actes retirent un produit du stock (ex. Gant), selon les Paramètres.
3. **Recettes par acte** : les patients enregistrés y sont comptés automatiquement (colonne *Patients*).
   Saisir dans *En plus* seulement les actes de patients **non enregistrés** (ex. 7 CPN).
   La touche **Entrée** passe à la ligne suivante.
4. **Ventes pharmacie** (ventes sans patient) :
   - choisir le produit et la quantité : le stock est diminué automatiquement ;
   - ou, si les ventes ne sont pas détaillées, laisser « Montant global », écrire un libellé et le total.
5. **Dépenses** : une ligne par dépense, avec la **catégorie**, le **motif**, le montant et, si possible,
   la **photo du reçu** (bouton « Justificatif »). La caisse qui paie est proposée selon la catégorie
   (ristournes échographie et divers pharmacie → caisse Pharmacie + Écho).
6. **Clôture** (le soir) : compter l'argent, saisir le montant compté et cliquer **Clôturer la journée**.
   L'application compare avec le montant attendu et signale tout écart.
   Après clôture, la journée ne peut plus être modifiée par la caisse.

> Une journée oubliée ? Menu **Journées** → choisir la date → **Ouvrir / saisir**.

### Ce que calcule le résumé

- **Caisse Entrées + Labo** = actes (y compris laboratoire)
  − commissions laboratoire reversées (prescripteurs 15 %, partenaire 60 %)
  − dépenses payées sur cette caisse.
  La part ONG AIP (25 %) reste en caisse.
- **Caisse Pharmacie + Écho** = échographies + ventes pharmacie − dépenses payées sur cette caisse.
- **Recette nette du jour** = somme des deux caisses (même calcul que la colonne « TOTAL DES RECETTE » de l'ancien Excel).
- **Argent attendu ce soir** = argent du matin + recette nette − versements bancaires du jour.

---

## Versements à la banque (Caissier)

Menu **Versements** → formulaire à droite : date, banque, montant, n° de bordereau et photo du bordereau.
Le tableau « Rapprochement par mois » montre, mois par mois, la recette nette et ce qui a été versé.

---

## Validation (Superviseur)

- Le **tableau de bord** liste les journées clôturées à valider, les écarts de caisse et les journées
  où les dépenses dépassent les recettes.
- Ouvrir la journée → vérifier → **Valider la journée** : elle est verrouillée.
- Pour corriger une journée clôturée ou validée : **Rouvrir pour correction…** avec un **motif obligatoire**.
  Toutes les modifications (qui, quand, avant → après) sont visibles dans **Journal d'activité**.

---

## Pharmacie (rôle Pharmacie)

- **Stock** : quantité disponible de chaque produit, valeur du stock, produits **à commander**
  (sous le seuil d'alerte défini sur la fiche produit).
- **Ajouter du stock** (achat direct, don) : ouvrir le produit → carte *Ajouter du stock* → quantité,
  date, prix d'achat (vide = dernier prix, 0 pour un don) et référence (n° de facture, donateur).
  À la création d'un produit, le champ *Stock initial* enregistre la quantité déjà présente.
- **Commandes** : *Nouvelle commande* → ajouter les produits → *Marquer comme commandée* → à la livraison,
  *Réceptionner* (corriger les quantités réellement reçues) : le stock augmente.
  Le bon de commande s'imprime avec le bouton *Imprimer*.
- **Inventaire** : saisir les quantités comptées ; les écarts sont enregistrés.
- **Sortie (perte, périmé)** : retirer du stock un produit périmé ou cassé, avec le motif.

---

## Rapports (tous les rôles)

- **Rapport mensuel** : synthèse jour par jour, vue *Détail par acte* (comme l'ancien tableau), activité
  du mois (nombre réel d'actes), commissions, dépenses par catégorie, argent en caisse et versements.
  Boutons **Excel** (fichier à envoyer) et **Imprimer / PDF**.
- **Rapport annuel** : chaque mois de l'année, nombre d'actes par mois, dépenses par catégorie, export Excel.
