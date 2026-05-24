# Spec 2 — Vue réseau globale (dashboard d'accueil admin)

- **Date** : 2026-05-24
- **Chantier** : dashboard
- **Statut** : validé
- **Contrainte** : LECTURE SEULE DB (aucune écriture, aucune migration).

## Contexte

Audience : **admin réseau / coopérative**. La page d'accueil actuelle (`index`,
`templates/index/index.html`) n'affiche que des compteurs bruts (nb wallets, cartes,
assets…). On la transforme en vraie **vue d'ensemble agrégée** du réseau.

## Périmètre — modules validés

1. Masse monétaire par monnaie
2. Top lieux
3. Activité récente réseau
4. Monnaie dormante de la **monnaie fédérée (FED) uniquement**

> Décision produit : la monnaie dormante **agrégée toutes-monnaies n'est PAS pertinente**
> (chaque lieu gère sa monnaie locale). Seule celle de la **monnaie fédérée** (l'asset
> `STRIPE_FED_FIAT`, monnaie inter-lieux du réseau) a du sens au niveau réseau.

## Maquette (indicative)

```
┌────────────────────────────────────────────────────────────┐
│  RÉSEAU — vue d'ensemble                                     │
├────────────────────────────────────────────────────────────┤
│  [ Masse monétaire par monnaie ]                            │
│   Fédérée (FED) : créé / circulation / lieux / banque        │
│   Monnaies locales (TLF, TNF) : 1 ligne / asset             │
│   Temps (TIM) en heures · Fidélité (FID)                    │
├──────────────────────────────┬─────────────────────────────┤
│  [ Top lieux ]               │  [ Monnaie dormante FÉDÉRÉE ]│
│   par volume tx + solde      │   total dormant (FED)        │
│   détenu                     │   → « Simuler la fonte »      │
├──────────────────────────────┴─────────────────────────────┤
│  [ Activité récente réseau ]                                │
│   volume global / temps  +  dernières transactions          │
└────────────────────────────────────────────────────────────┘
```

## Détail des modules

### Module A — Masse monétaire par monnaie
- Total réseau + **1 ligne par asset** (non archivé) : créé / en circulation / dans les
  lieux / remis en banque.
- **Groupé par catégorie** (Fédérée, Locales, Temps, Fidélité…).
- Unités par catégorie (cf Spec 1).
- Réutilise les agrégats `Asset.total_*` ; attention à ne pas faire N+1 sur la liste d'assets.

### Module B — Top lieux
- Classement des `Place` par :
  - **volume de transactions** (count/sum agrégés) ;
  - **solde détenu** (somme des tokens du wallet du lieu).
- Top N (ex : 10).
- Requête agrégée avec `annotate` sur `Place` (pas de boucle Python qui requête).

### Module C — Activité récente réseau
- **Courbe volume global dans le temps** (toutes monnaies, par mois) — même logique que
  `_calcul_temporel` mais sans filtre asset (attention : agréger proprement, exclure `FIRST`).
- **Flux des X dernières transactions** toutes monnaies, avec `select_related` anti-N+1.

### Module D — Monnaie dormante fédérée
- Calcul « monnaie fondante » sur le **seul** asset `FED` (`category=STRIPE_FED_FIAT`).
- Affiche le total dormant + bouton/lien **« Simuler la fonte »** → renvoie vers le
  simulateur (Spec 3) sur la page de l'asset FED.

## Architecture / données
- Une fonction `get_dashboard_reseau()` en cache (TTL court, ex 5 min) qui agrège les 4 modules.
- **Tout en agrégats annotés** (zéro N+1). La base de dev est petite mais on conçoit pour la prod.
- Graphes : Chart.js déjà vendorisé ; le graphe volume réseau réutilise `fedow_charts.js`.

## Fichiers touchés
| Fichier | Changement |
|---|---|
| `fedow_dashboard/views.py` | `index` enrichi + `get_dashboard_reseau()` + helpers |
| `fedow_dashboard/templates/index/index.html` | refonte en vue d'ensemble |
| `fedow_dashboard/templates/index/partials/*.html` | partials par module (optionnel) |
| `fedow_dashboard/static/js/fedow_charts.js` | graphe volume réseau |

## Lecture seule
Agrégations `SELECT` uniquement. Aucune écriture, aucune migration.

## Vérification
- `manage.py check`.
- Shell read-only : compter les requêtes de `get_dashboard_reseau` (constant, pas de N+1).
- Curl `/dashboard/` → HTTP 200, présence des 4 modules, unités correctes.
