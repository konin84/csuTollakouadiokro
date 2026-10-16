# CSU Caisse – Guide d'utilisation

Ouvrir le navigateur (Chrome, Edge, Firefox) sur l'adresse donnée par l'administrateur,
par exemple `http://192.168.1.10`, puis se connecter avec son identifiant.

---

## La journée de caisse (Caissier)

1. Menu **Journée du jour** → **Ouvrir la journée du jour**.
2. **Patients du jour** : à chaque patient, cliquer **+ Nouveau patient** :
   - saisir le **nom et prénoms** (téléphone, sexe et âge si possible) ;
   - **ajouter les actes** : le prix du tarif du jour s'affiche, le montant est calculé
     (chaque examen de laboratoire est un acte avec son prix) ;
   - **ajouter les produits** vendus : le stock restant s'affiche ; une quantité supérieure au stock est refusée ;
   - **Enregistrer** : le reçu numéroté s'affiche → **Imprimer le reçu** → **+ Patient suivant**.
   Un reçu se **modifie** tant que la journée est ouverte. En cas d'erreur, l'**annuler** avec un motif
   (il reste visible, barré, et n'est plus compté ; les produits reviennent en stock).
3. **Recettes par acte** : calculées automatiquement à partir des reçus ; chaque acte doit donc passer par
   un reçu patient. La liste **Patients du jour** affiche les 20 derniers reçus ; les boutons
   *Plus anciens* / *Plus récents* parcourent les autres.
4. **Ventes pharmacie** : la liste des médicaments vendus dans la journée. Pour un client venu **seulement
   pour des médicaments**, cliquer **+ Vente de médicaments** : même formulaire que le patient, sans les actes
   (le nom du client est facultatif). Un reçu numéroté est imprimé et le stock diminue.
5. **Dépenses** (par le **superviseur**) : une ligne par dépense, avec la **catégorie**, le **motif**, le montant et, si possible,
   la **photo du reçu** (bouton « Justificatif »). La caisse qui paie est proposée selon la catégorie
   (ristournes échographie et divers pharmacie → caisse Pharmacie + Écho).
6. **Clôture** (le soir, par le **superviseur**) : le caissier apporte l'argent au superviseur, qui le compte,
   saisit le montant compté et clique **Clôturer la journée**.
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

## Remise de l'argent au superviseur (Caissier → Superviseur)

Le soir, le caissier remet **tout** l'argent au superviseur, qui clôture la journée (voir ci-dessus).
Il saisit ensuite l'argent reçu dans **Argent reçu du caissier**
(pré-rempli avec l'argent compté à la clôture) puis clique **Valider la journée**.
Si le montant reçu est différent, l'écart de remise est affiché sur la journée, signalé au tableau de bord
et conservé dans le journal d'activité.

## Versements à la banque (Superviseur)

Menu **Versements bancaires** → formulaire à droite : date, banque, montant, n° de bordereau et photo du
bordereau. La carte **Argent chez le superviseur** montre ce qui reste à verser (remises reçues − versements).
Le tableau « Rapprochement par mois » montre, mois par mois, la recette nette, l'argent remis au superviseur
et ce qui a été versé.

---

## Validation (Superviseur)

- Le **tableau de bord** liste les journées clôturées à valider, les écarts de caisse et les journées
  où les dépenses dépassent les recettes.
- Ouvrir la journée → vérifier → saisir l'**argent reçu du caissier** → **Valider la journée** :
  elle est verrouillée.
- **Actes médicaux** (menu Administration) : créer un acte avec son prix (chaque examen de laboratoire a le sien), le modifier, changer son tarif à une date donnée,
  le désactiver, ou le supprimer s'il n'a jamais été facturé.
- Pour corriger une journée clôturée ou validée : **Rouvrir pour correction…** avec un **motif obligatoire**.
  Toutes les modifications (qui, quand, avant → après) sont visibles dans **Journal d'activité**.

---

## Pharmacie (rôle Pharmacie)

La caisse et la pharmacie sont séparées : le **Caissier** ne voit pas les menus Stock, Commandes,
Inventaire et Fournisseurs (il vend toujours les produits sur le reçu du patient), et le rôle
**Pharmacie** ne voit pas les journées de caisse ni les versements. Les ventes passent par la caisse.

- **Stock** : quantité disponible de chaque produit, valeur du stock, produits **à commander**
  (sous le seuil d'alerte défini sur la fiche produit).
- **Conditionnement** (fiche produit) : le stock est compté dans la **plus petite unité vendue** (ex. comprimé).
  Pour un produit acheté par boîte et vendu par plaquette, remplir aussi :
  *unité d'achat* « boîte » et *unités de stock par unité d'achat* 100 ; *autre unité de vente* « plaquette »,
  *unités de stock par unité de vente* 10 et son *prix de vente*. Le *prix d'achat* est alors le prix d'une boîte.
  Commandes, réceptions et ajouts de stock se saisissent **en boîtes** ; à la caisse, chaque produit se vend
  **au comprimé ou à la plaquette** (colonne « Vendu par ») ; inventaire et pertes se comptent **en comprimés**.
- **Ajouter du stock** (achat direct, don) : ouvrir le produit → carte *Ajouter du stock* → quantité,
  date, prix d'achat (vide = dernier prix, 0 pour un don) et référence (n° de facture, donateur).
  À la création d'un produit, le champ *Stock initial* enregistre la quantité déjà présente.
- **Commandes** : *Nouvelle commande* → ajouter les produits → *Marquer comme commandée* → à la livraison,
  *Réceptionner* (corriger les quantités réellement reçues) : le stock augmente.
  Le bon de commande s'imprime avec le bouton *Imprimer*.
- **Inventaire** : saisir les quantités comptées ; les écarts sont enregistrés.
- **Sortie (perte, périmé)** : retirer du stock un produit périmé ou cassé, avec le motif.

---

## Rapports

- **Rapport mensuel** (Caissier, Superviseur, Consultation) : synthèse jour par jour, vue *Détail par acte* (comme l'ancien tableau), activité
  du mois (nombre réel d'actes), commissions, dépenses par catégorie, argent en caisse et versements.
  Boutons **Excel** (fichier à envoyer) et **Imprimer / PDF**.
- **Rapport annuel** (Caissier, Superviseur, Consultation) : chaque mois de l'année, nombre d'actes par mois, dépenses par catégorie, export Excel.
- **Rapport de stock** (Pharmacie, Superviseur) : pour chaque produit, le stock au début du mois, les entrées,
  les quantités vendues, perdues et ajustées à l'inventaire, le stock et sa valeur
  en fin de mois ; produits à commander ; détail des entrées, pertes et ajustements. Excel et Imprimer / PDF.
