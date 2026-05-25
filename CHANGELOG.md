# Changelog — Fedow

Toutes les évolutions notables du projet. Format bilingue FR/EN, le plus récent en haut.
/ All notable changes. Bilingual FR/EN, most recent on top.

---

## Remboursement en ligne — clé d'idempotence Stripe (anti double-remboursement) — 2026-05-25

**Quoi / What:** `CheckoutStripe.refund_payment_intent` accepte une `idempotency_key`,
et `wallet/refund_fed_by_signature` la fournit par (checkout, montant) :
`refund:{checkout.uuid}:{amount}`. Deux tentatives **identiques** (double-clic /
requête rejouée) ne déclenchent **qu'UN seul** remboursement Stripe (fenêtre 24 h).
/ Per-(checkout, amount) Stripe idempotency key on the online refund: duplicate
attempts collapse into a single Stripe refund.

**Why:** Incident festival (trace `dfb487…`) : double-tap sur
`/my_account/refund_online/` (iPhone, réseau saturé) → deux remboursements
concurrents. Le registre était déjà protégé par l'assert `REFUND` (pas de
double-écriture en base), mais l'appel Stripe partait **avant** l'assert → risque
de double versement Stripe non tracé en multi-recharges. La clé ferme ce risque.

**Limite connue / Known limit:** la clé couvre le rejeu du **même** checkout. Le cas
multi-recharges où la 2ᵉ requête vise un **autre** checkout (après bascule de statut)
demanderait un verrou par wallet (memcache) — **non implémenté** (décision : minimal).

### Fichiers modifiés / Modified files
| Fichier / File | Changement / Change |
|---|---|
| `fedow_core/models.py` | `refund_payment_intent(self, amount, idempotency_key=None)` → transmis à `stripe.Refund.create` |
| `fedow_core/views.py` | `refund_fed_by_signature` : clé `refund:{checkout.uuid}:{amount}` |

## OrganizationAPIKey — FK `place` et `user` en PROTECT (anti-suppression silencieuse) — 2026-05-25

**Quoi / What:** Les deux FK `place` et `user` de `OrganizationAPIKey` passent de
`CASCADE` à **`PROTECT`**. Supprimer un user (ou une place) qui porte encore une
clé d'organisation lève désormais `ProtectedError`, au lieu d'effacer la clé en
silence.
/ Both `OrganizationAPIKey` FKs (`place`, `user`) switched from `CASCADE` to
`PROTECT`. Deleting a user (or place) that still owns an org key now raises
`ProtectedError` instead of silently deleting the key.

**Why:** Incident prod (tenant Lespass « sophie-houot ») : la suppression du
**compte user admin** d'un lieu avait CASCADE-supprimé sa clé d'organisation et
vidé `place.admins`, **la place restant intacte** — d'où un diagnostic non
évident. Résultat : appairage cassé → `wallet/get_or_create` en **403**
(`HasOrganizationAPIKeyOnly`) → login Lespass en **500**. `PROTECT` force une
opération **délibérée** (retirer/réémettre la clé avant de supprimer le compte).
/ Prod incident: deleting a place's admin user CASCADE-deleted its org key and
emptied `place.admins` while the place stayed intact — hard to diagnose. Broke
pairing → 403 on `wallet/get_or_create` → 500 on the Lespass login. PROTECT forces
a deliberate key removal first.

### Migration
- `0023_alter_organizationapikey_place_and_more` — deux `AlterField`.
- **No-op au niveau schéma** : `on_delete` est géré par l'ORM Django, pas par une
  contrainte SQL. `migrate` requis seulement pour la cohérence de l'état des
  migrations. / Schema-level no-op; `migrate` only for migration-state consistency.

### Remise en service d'un lieu cassé / Restoring a broken place
Recréer l'admin + réémettre une clé côté Fedow, puis la stocker (chiffrée) côté
Lespass : `get_or_create_user(email)` → `place.admins.add(user)` →
`OrganizationAPIKey.objects.create_key(name=f"lespass_{place.name}:{user.email}", place=place, user=user)`
→ côté Lespass `FedowConfig.set_fedow_place_admin_apikey(key)` + `save()`.

### Fichiers modifiés / Modified files
| Fichier / File | Changement / Change |
|---|---|
| `fedow_core/models.py` | `OrganizationAPIKey.place` et `.user` : `CASCADE` → `PROTECT` |
| `fedow_core/migrations/0023_alter_organizationapikey_place_and_more.py` | Migration (2 `AlterField`) |

## Dashboard Fedow — frais Stripe & recette de fonte nette — 2026-05-25

**Quoi / What:** Intégration des **frais Stripe** dans la page asset FED : nouvelle carte
**« Bilan Stripe ↔ fonte »** et recette de fonte affichée **nette** (barres nettes + ligne
rouge des frais). Suite directe de la projection de fonte du 2026-05-24.
**Why:** Les frais Stripe sont payés à la recharge (et prélevés côté Stripe, invisibles dans
Fedow) ; ils grèvent la totalité du rechargé. La fonte sert à les rembourser → on montre le
**récupérable net** et si la fonte **couvre** les frais.

**Contrainte / Constraint:** **LECTURE SEULE.** Frais **recalculés** (jamais stockés) ; le
solde réel du compte Stripe reste hors Fedow.

### Cadrage comptable retenu
- Frais payés **à la recharge**, pas à la fonte (mouvement interne de token, sans frais).
- Sur l'argent **dépensé** → frais perdus (encaissé ~98 %, remboursé 100 % aux lieux). Sur le
  **dormant fondu** → récupéré. **Récupérable net = fonte − frais sur la totalité du rechargé.**
- Une cohorte presque entièrement dépensée peut être **à perte** (frais > son dormant) ;
  globalement positif tant que le dormant accumulé dépasse les frais.

### Commande `courbe_survie`
- Publie en plus **`refill_par_age`** (montant total rechargé par âge de cohorte) → frais par cohorte.

### Carte « Bilan Stripe ↔ fonte » (`asset_transactions.html` + `fedow_simulateur.js`)
- **Taux de frais effectif** saisissable (`sim-frais`, défaut **2 %**) → recalcul direct du
  bilan ET du graphe. Paramétrable car le canal **TPE WisePOS** n'est pas distinguable en base
  (toutes les recharges ont une `checkout_session`) et le tarif peut être négocié.
  Tarifs Stripe FR de référence : en ligne **1,5 % + 0,25 €**, TPE WisePOS **1,4 % + 0,10 €**.
- Affiche : rechargé (cumul), frais Stripe, fonte au seuil, **récupérable net**, **couverture**
  des frais par la fonte (< 100 % = encore à perte).

### Recette de fonte affichée NETTE
- Barres = **fonte − frais Stripe** de la cohorte, 2 modes (tout / 1 €/mois) ; **ligne rouge** =
  frais Stripe de la cohorte (déjà déduits). Au pic festival, la ligne rouge approche la barre
  (un festival génère beaucoup de frais mais peu de dormant).
- **Correctif de méthode** : la fonte d'une cohorte se calcule sur sa **recharge × survie(seuil)**
  (cohortes < seuil) ou sur le **stock réel** (cohortes déjà au-delà du seuil) — et non sur le
  stock résiduel, qui sous-estimait le mois courant (partiel) et créait des barres négatives.

### Fichiers modifiés / Modified files
| Fichier / File | Changement / Change |
|---|---|
| `fedow_core/management/commands/courbe_survie.py` | sortie `refill_par_age` (+ `nb_cartes` déjà présent) |
| `fedow_dashboard/views.py` | `_charge_courbe_survie` transmet `refill_par_age` + `total_refill_centimes` |
| `fedow_dashboard/templates/asset/asset_transactions.html` | carte « Bilan Stripe ↔ fonte », input taux, barres nettes |
| `fedow_dashboard/static/js/fedow_simulateur.js` | bilan, recette nette, ligne rouge des frais, calcul recharge × survie |

### Migration
- **Migration nécessaire / Migration required:** **Non.**

### Note déploiement
- Après modif **JS** → `collectstatic` ; **template / vue** → reload gunicorn ; rafraîchir la
  courbe → `python manage.py courbe_survie`.

## Dashboard Fedow — projection de la recette de fonte (courbe de survie) — 2026-05-24

**Quoi / What:** Ajout d'une commande de gestion `courbe_survie` (calcul *offline* de la
courbe de survie de la monnaie fédérée → fichier JSON) et refonte de la carte de fonte du
dashboard en **« Recette de fonte attendue »** : un graphe en barres qui projette, mois par
mois, ce qu'une fonte rapporterait sur l'argent **déjà rechargé**.
**Why:** Répondre à « combien va-t-on toucher dans X mois ? » à partir des recharges
**réelles** déjà encaissées, sans deviner les festivals futurs.

**Contrainte transverse / Cross-cutting constraint:** **LECTURE SEULE en base.** La commande
lit la chaîne et écrit un fichier ; la vue lit ce fichier. Aucune écriture en base, aucune migration.

### Commande de gestion `courbe_survie` (`fedow_core/management/commands/courbe_survie.py`, nouveau)
- Parcourt les transactions FED dans l'ordre du temps ; **FIFO par carte** (chaque dépense
  consomme l'argent le plus ancien) → durée de vie de chaque euro chargé.
- En déduit une **courbe de survie** `S(âge)` par **Kaplan-Meier discret** (taux de dépense
  par mois d'âge, gère la censure → neutralise le biais de saisonnalité des festivals).
- Écrit `database/courbe_survie.json` : `survie` (S par mois), `stock_par_age`
  (`montant_centimes` + `nb_cartes` du stock actuel par âge), totaux. **FED uniquement.**
- À **relancer à la main** pour rafraîchir (`python manage.py courbe_survie`, option `--horizon`).
- Résultat prod observé : ~89 % d'une recharge dépensée le 1er mois, **survie ≈ 6,8 % à 12 mois**
  (≈ taux de dormance durable), revenu de fonte récurrent ≈ volume annuel × ~7 %.

### Carte « Recette de fonte attendue » (`asset/asset_transactions.html` + `fedow_simulateur.js`)
- Remplace l'ancien simulateur « solde restant » **et** la projection run-off heuristique
  (les deux supprimés). Un seul moteur : la courbe de survie.
- **Graphe en barres** : chaque tranche d'argent devient « fondable » quand son âge atteint
  le seuil ; la barre du mois `D+seuil` = `montant × survie(seuil)`. Les festivals passés
  forment des **pics futurs** (ex : août 2025 → pic à +14 mois).
- **Zone certaine uniquement [0, +seuil]** : 100 % basée sur l'argent déjà encaissé, aucune
  spéculation sur les recharges à venir.
- **2 séries comparées** : « tout d'un coup » vs « 1 €/mois » (étalé via `nb_cartes`).
- Pilotage temps réel (client) : **seuil** (décale les barres + change le taux capté),
  **montant fixe**, **fenêtre d'affichage**. KPI : total par mode, déjà fondable, cartes concernées.
- Vue : helper `_charge_courbe_survie(asset)` lit le JSON (aucune requête base), passé en
  contexte caché. Dégradation propre si le JSON n'existe pas (monnaies locales).

### Autres
- **`django_browser_reload` désactivé** (middleware commenté dans `settings.py`, réversible) :
  plus de rechargement automatique de page.

### Fichiers modifiés / Modified files
| Fichier / File | Changement / Change |
|---|---|
| `fedow_core/management/commands/courbe_survie.py` | **nouveau** — calcul de la courbe de survie + stock par âge → JSON |
| `fedow_dashboard/views.py` | helper `_charge_courbe_survie`, ajout au contexte caché de `get_dashboard_asset` |
| `fedow_dashboard/templates/asset/asset_transactions.html` | carte « Recette de fonte attendue » (barres), `json_script` `data-courbe-survie` |
| `fedow_dashboard/static/js/fedow_simulateur.js` | projection en barres (2 modes), suppression des courbes/run-off |
| `fedowallet_django/settings.py` | `django_browser_reload` (middleware) désactivé |

### Migration
- **Migration nécessaire / Migration required:** **Non** (lecture seule, aucun modèle modifié).

### Note déploiement / Deployment note
- Rafraîchir la courbe : `docker exec fedow_django poetry run python manage.py courbe_survie`.
- Modif **JS/CSS** → `collectstatic` ; modif **template / vue / settings** → reload gunicorn
  (`docker exec fedow_django pkill -HUP gunicorn`).

## Dashboard Fedow — enrichissement (admin réseau) — 2026-05-24

**Quoi / What:** Refonte et enrichissement du `fedow_dashboard` (page d'accueil réseau +
page détail d'un asset) avec des informations utiles pour un admin réseau / coopérative.
**Pourquoi / Why:** Le dashboard ne montrait que des compteurs bruts ; on expose désormais
la masse monétaire, le cycle de vie, la monnaie dormante, un simulateur de fonte, des
moyennes par portefeuille, le breakage et une projection.

**Contrainte transverse / Cross-cutting constraint:** **LECTURE SEULE en base** (aucune
écriture, aucune migration). Tous les calculs sont des agrégations `SELECT`, mis en cache
(memcached), conçus **sans N+1** (vérifié : requêtes constantes même sur 42 938 transactions).

### Page détail asset (`asset/asset_transactions.html`, assets hors adhésion/badgeuse)
- **Cartes KPI** : créé / en circulation / dans les lieux / remis en banque.
- **Cycle de vie** : barre empilée CSS (où se trouve la monnaie). Correctif locale :
  `|unlocalize` sur les largeurs CSS (la virgule décimale fr cassait `style="width:x%"`).
- **Monnaie fondante** : courbe Chart.js du cumul dormant par seuil d'inactivité.
  `_calcul_monnaie_fondante` en **O(wallets)** (2 `GROUP BY` `Max(datetime)`), renvoie une
  liste anonymisée `wallets_dormants = [(âge_jours, solde_centimes)]` + `depense_totale`,
  `nb_vides`, `total_charge`.
- **Simulateur de fonte** (`fedow_simulateur.js`, 100 % client, zéro requête) : 2 modes en
  **boutons radio** (montant fixe / totalité du portefeuille), curseur seuil d'inactivité
  (défaut 14 mois) + horizon. Courbe = **solde dormant restant** (décroissant). Accordéon
  d'aide « Comment ça marche ? ».
- **Projection à 12 mois (run-off)** : heuristique **indicative** (> 12 mois = breakage
  quasi-permanent, le reste s'écoule linéairement) — courbe + KPI « sortira / restera ».
- **Moyennes par portefeuille** (après le simulateur, dynamiques, pilotées par le curseur
  seuil) : dépense moyenne, solde moyen (détenteurs **et** par carte distribuée), médiane,
  comparaison actifs/inactifs (moyenne + médiane), % de la masse dormante, compteur
  détenteurs / vidées.
- **Breakage (rétention)** : taux de breakage global + snapshot du solde par tranche d'âge.
- **Graphe temporel** : barres empilées Chart.js par mois et par action. **Exclut `FIRST`
  (genèse) et `CREATION` (frappe)** pour ne pas double-compter les recharges ; mois continus.
- **Dernières transactions** : repliables (`<details>`) ; retrait de la re-vérification
  `verify_hash` par ligne (intégrité garantie à l'écriture + Sentry) ; `select_related`
  anti-N+1.

### Page d'accueil réseau (`index/index.html`, `get_dashboard_reseau()` en cache)
- **Masse monétaire par monnaie** groupée par catégorie, code **couleur** par catégorie
  (`COULEUR_CATEGORIE`), **fiduciaire fédérée en premier**. Exclut adhésions (`SUB`) et
  badgeuses (`BDG`). Sommes par asset (jamais de total inter-monnaies).
- **Top lieux** par nombre de transactions (+ solde indicatif toutes monnaies).
- **Activité récente** : pouls mensuel (nombre de transactions, agnostique à l'unité) +
  dernières transactions.
- **Monnaie fédérée dormante** (FED uniquement) + lien vers le simulateur.
- Compteurs (Monnaies hors SUB/BDG, Fédérations, Lieux, Portefeuilles, Cartes).

### Transverse
- **Unités par catégorie** : filtre `unite_asset` (monnaie temps en « H », fidélité en
  « pts », sinon code devise). `intcomma` + chiffres tabulaires.
- **Accès** : `@staff_member_required` sur `asset_view` et `place_view` (redirige vers
  `/admin/login/`) ; la home `/` reste publique.
- **Thème clair par défaut** + mémorisation du choix en `sessionStorage` (`base.html`,
  blocs `{% block extra_css %}` / `{% block extra_js %}` ajoutés).
- **Chart.js** vendorisé localement (`static/js/chart.umd.4.4.1.min.js`).

### Fichiers modifiés / Modified files
| Fichier / File | Changement / Change |
|---|---|
| `fedow_dashboard/views.py` | helpers de calcul (cycle de vie, monnaie fondante O(wallets), temporel, réseau), `get_dashboard_asset` / `get_dashboard_reseau` en cache, `index` réécrit, auth sur `asset_view`/`place_view` |
| `fedow_dashboard/templates/asset/asset_transactions.html` | refonte complète (KPI, cycle, fondante, breakage, simulateur, projection, moyennes, temporel, transactions repliables) |
| `fedow_dashboard/templates/index/index.html` | vue réseau (masse, top lieux, activité, dormance FED) |
| `fedow_dashboard/templates/base.html` | blocs extra_css/extra_js, thème clair + sessionStorage |
| `fedow_dashboard/templatetags/fedow_dashboard_tags.py` | filtre `unite_asset` |
| `fedow_dashboard/static/js/fedow_charts.js` | graphes fondante / temporel / pouls réseau |
| `fedow_dashboard/static/js/fedow_simulateur.js` | simulateur + moyennes + breakage + projection run-off |
| `fedow_dashboard/static/js/chart.umd.4.4.1.min.js` | Chart.js v4.4.1 vendorisé (nouveau) |

### Migration
- **Migration nécessaire / Migration required:** **Non** (aucun changement de modèle,
  lecture seule).

### Note déploiement / Deployment note
- Modif **template / vue Python** → reload gunicorn (`docker exec fedow_django pkill -HUP
  gunicorn`) car `cached.Loader` actif (DEBUG=False) ; modif **JS/CSS** → `collectstatic`
  (servi par nginx via le volume partagé `../Fedow/www:/www`).
