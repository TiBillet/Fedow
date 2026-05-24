# Spec 3 — Simulateur de fonte (demurrage)

- **Date** : 2026-05-24
- **Chantier** : dashboard
- **Statut** : validé
- **Contrainte** : LECTURE SEULE DB. Le simulateur **projette**, il ne modifie aucun solde.

## Concept

Une **monnaie fondante** perd de la valeur si elle est thésaurisée (idée de Silvio Gesell ;
ex. le Chiemgauer ~8 %/an), pour encourager la **circulation** plutôt que la thésaurisation.
Le montant « fondu » revient au réseau.

On ne **fond rien** (lecture seule). On construit un **outil « et si ? »** : on règle une
politique de fonte et on voit ce qu'elle *rapporterait* et ce qu'elle *concernerait*.

## Emplacement
- Dans la section « monnaie fondante » de la page asset :
  - sur l'asset **FED** → simulateur **niveau réseau** ;
  - sur chaque asset **local** → simulateur **niveau lieu**.
- La vue réseau (Spec 2, Module D) renvoie vers le simulateur de la FED.

## Entrées (contrôles UI)
- **Mode de politique** (3 choix) :
  | Mode | Règle | Calcul |
  |---|---|---|
  | % par mois | ex : 2 %/mois sur wallets > seuil | décroissance géométrique |
  | Montant fixe / mois | ex : *inactif > 14 mois → 1 €/mois* (plafonné au solde) | linéaire, par wallet |
  | Tout prendre | après le seuil, le solde dormant est entièrement récupéré | one-shot (péremption) |
- **Seuil d'inactivité** : curseur **libre** (1 à 36 mois).
- Selon le mode : un curseur **taux %** ou un champ **montant fixe**.
- **Horizon de projection** : 12 mois par défaut.

## Sorties (calculées en JS, en direct)
- **Recette réseau** : ce mois-ci + cumulé sur l'horizon.
- **Volume de monnaie concerné** : solde dormant éligible (≥ seuil) + **nombre de wallets** touchés.
- **Courbe de fonte cumulée** (Chart.js).

> On affiche **les deux lectures** (recette ET volume), comme validé.

## Calcul — 100 % côté client, sur donnée serveur read-only
- Le serveur renvoie (via `json_script`) une liste **anonymisée** des wallets dormants :
  `[(âge_jours, solde_centimes), …]` — **sans user, sans uuid** (produite par l'optimisation
  de la Spec 1).
- Le JS filtre par seuil puis applique le mode :
  - **%** : `melt[i] = solde_restant × taux ; solde_restant -= melt[i]` (par pas mensuel).
  - **fixe** : par wallet éligible, `min(montant, solde)` chaque mois ; décrémente.
  - **tout** : `recette = somme(soldes éligibles)` (one-shot).
- Recalcul **instantané** au mouvement des curseurs. **Zéro requête** par manipulation.

### Exemple de validation
Asset avec 30 000 unités dormantes (> 6 mois), mode 2 %/mois :
- Mois 1 : 30 000 × 2 % = 600 ; reste 29 400.
- Mois 2 : 29 400 × 2 % = 588 …
- Sur 12 mois : ≈ 6 460 unités récupérées (décroissance géométrique).

## Architecture / fichiers
| Fichier | Changement |
|---|---|
| `fedow_dashboard/views.py` | ajouter la liste anonymisée `(âge, solde)` au contexte (depuis Spec 1) + `json_script` |
| `fedow_dashboard/templates/asset/asset_transactions.html` | section simulateur : contrôles + canvas + sorties |
| `fedow_dashboard/static/js/fedow_simulateur.js` (nouveau) | logique des 3 modes, mise à jour live |

## Lecture seule & confidentialité
- **Aucune écriture** : le simulateur ne touche pas aux soldes, il projette.
- Donnée **anonymisée** (âge + solde uniquement). Dashboard admin.

## Vérification
- JS : vérifier les 3 modes sur un jeu connu (ex. 30 000 @ 2 % → 600 le 1er mois).
- Page asset → HTTP 200 ; curseurs réactifs sans requête réseau (vérifier l'onglet Network).
