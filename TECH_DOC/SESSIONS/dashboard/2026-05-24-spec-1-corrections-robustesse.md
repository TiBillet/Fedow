# Spec 1 — Corrections & robustesse du tableau de bord asset

- **Date** : 2026-05-24
- **Chantier** : dashboard
- **Statut** : validé, prêt à implémenter
- **Contrainte** : LECTURE SEULE DB (aucune écriture, aucune migration). On ne touche qu'au dashboard.

## Contexte

La page asset (`/dashboard/asset/<uuid>/`, template `asset/asset_transactions.html`)
a été enrichie (KPI, cycle de vie, monnaie fondante, graphe temporel). Une relecture
critique a révélé des corrections d'hygiène et de robustesse à faire **avant** d'empiler
de nouvelles fonctionnalités.

## Changements

### 1. Exclure le bloc FIRST du graphe temporel
- `_calcul_temporel` inclut l'action `FIRST` (bloc de genèse, montant 0) → série
  « Premier bloc » parasite.
- **Correctif** : `.exclude(action=Transaction.FIRST)` dans la requête de `_calcul_temporel`.

### 2. Séparer CREATION et REFILL sans double-compte
- Une recharge = **2 transactions** : `CREATION` (le lieu *frappe* la monnaie, adossée
  à l'euro) puis `REFILL` (le lieu *verse* sur le wallet de l'user).
- `_calcul_cycle_de_vie` : « créé » = `CREATION` seul → **déjà correct**, pas de double-compte.
- **Graphe temporel** : aujourd'hui `CREATION` + `REFILL` sont empilés → une recharge de
  10 € paraît 20 € de « volume ».
- **Approche retenue** (ajustable en implémentation) : ne pas mélanger la *frappe*
  (`CREATION`) avec la *circulation*. Le graphe « volume » empile les flux de circulation
  (`REFILL`, `SALE`, `QRCODE_SALE`, `SUBSCRIBE`, `REFUND`, `DEPOSIT`) ; `CREATION` est
  affichée **distinctement** (série/ligne séparée « monnaie frappée »), pas dans la même pile.

### 3. Combler les mois vides (axe temporel continu)
- Aujourd'hui les mois sans transaction sont écrasés → tendance mensongère (janvier et mars
  collés si février vide).
- **Correctif** : générer tous les mois entre le premier et le dernier mois présents,
  remplir les manquants à 0.

### 4. Unités par catégorie d'asset
- **Étape 0 (lecture seule)** : investiguer comment la valeur d'un asset `TIM` (monnaie temps)
  est stockée dans `Token.value` (centimes ? minutes ?) avant de décider l'affichage.
- `TIM` → heures (ou heures/minutes). `BDG` → passages / heures. Fiduciaires
  (`TLF`, `TNF`, `FED`, `FID`) → devise (euros, `/100`).
- **Implémentation** : un helper d'affichage qui choisit l'unité selon `asset.category`.
  Le filtre `dround` reste pour les fiduciaires.

### 5. Formatage lisible des nombres
- `intcomma` (lib `humanize`, déjà chargée) pour les séparateurs de milliers.
- Chiffres tabulaires : CSS `font-variant-numeric: tabular-nums` sur les colonnes de chiffres.

### 6. Optimiser `_calcul_monnaie_fondante` : O(transactions) → O(wallets)
- Aujourd'hui : charge **toutes** les transactions de l'asset en Python pour reconstruire
  la date de dernière activité par wallet. Lourd à l'échelle d'un festival.
- **Cible** : 2 requêtes agrégées
  - `Transaction.objects.filter(asset=asset).exclude(action=FIRST).values('sender').annotate(last=Max('datetime'))`
  - idem pour `receiver`
  - fusion en Python : `last_activite[w] = max(...)` → **O(wallets distincts)**.
- **Bonus** : la fonction renvoie aussi la liste **anonymisée** `(âge_jours, solde_centimes)`
  des wallets dormants → réutilisée telle quelle par le simulateur (Spec 3).
- Rappel sémantique (validé) : « inactif » = dernière transaction en émetteur **ou** receveur.
  Une recharge sans dépense compte donc comme actif. C'est **voulu**.

### 7. Retirer `verify_hash()` du tableau des transactions
- `verify_hash()` est rappelé **50× à chaque rendu** (re-hash CPU), inutile : l'intégrité de
  la chaîne est vérifiée **à l'écriture** (`Transaction.save()` valide la transaction
  précédente) et les erreurs remontent dans **Sentry**.
- **Correctif** : retirer la re-vérification par ligne (garder éventuellement l'affichage du
  hash court, sans re-calcul). Plus stable, plus simple.

### 8. Cache — pas de sur-ingénierie
- Garder le TTL de 5 min sur `get_dashboard_asset`. `Federation.save()` fait déjà
  `cache.clear()` global. Aucune invalidation fine à ajouter pour l'instant.

## Fichiers touchés
| Fichier | Changement |
|---|---|
| `fedow_dashboard/views.py` | `_calcul_temporel` (exclure FIRST, mois continus, séparer CREATION) ; `_calcul_monnaie_fondante` (2 GROUP BY + liste anonymisée) ; helper unités |
| `fedow_dashboard/templates/asset/asset_transactions.html` | unités par catégorie, `intcomma`, chiffres tabulaires, retrait re-vérif hash |
| `fedow_dashboard/templatetags/fedow_dashboard_tags.py` | filtre d'unité éventuel |
| `fedow_dashboard/static/js/fedow_charts.js` | libellés d'axes/unités |

## Lecture seule
Toutes les modifications sont des `SELECT`/agrégations + affichage. Aucune écriture DB,
aucune migration.

## Vérification
- `manage.py check`.
- Shell read-only avec `CaptureQueriesContext` : confirmer que `_calcul_monnaie_fondante`
  fait un nombre de requêtes **constant** indépendant du volume.
- Curl pages asset `TLF`, `FED`, `TIM` → HTTP 200 ; vérifier l'unité (TIM en heures),
  l'absence de la série « Premier bloc », et l'absence de double-compte des recharges.
