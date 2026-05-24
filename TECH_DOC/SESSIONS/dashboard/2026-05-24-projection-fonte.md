# Projection de la recette de fonte — courbe de survie (2026-05-24)

> Suite de `2026-05-24-session-recap-et-suite.md`. Cette session a tranché la « discussion
> ouverte » (§4 de ce doc) : on a fusionné simulateur + projection, puis pivoté vers une
> **projection de la recette de fonte** alimentée par une vraie courbe de survie.

## 0. Règles (rappel)

- **LECTURE SEULE en base.** La commande lit la chaîne et écrit un fichier JSON ; la vue lit
  ce fichier. Aucune écriture en base, aucune migration. **Reconfirmer avant chaque modif.**
- **Aucun commit, jamais de co-authored.** Aucune opération git sans accord explicite.

## 1. La question à laquelle on répond

« Sur l'argent **déjà rechargé**, combien une fonte rapporterait-elle, **mois par mois**, dans
le futur ? » — sans deviner les festivals à venir.

Idée clé (validée avec le mainteneur) : ~7 % d'une recharge finit dormante/fondable. Donc une
recharge de volume `V` au mois `D` produira, au mois `D + seuil`, une recette ≈ `V × survie(seuil)`.
En agrégeant **les recharges passées** décalées de `seuil`, on obtient des **pics futurs** calés
sur les festivals (ex : festival d'août 2025 → pic de recette ~14 mois plus tard).

## 2. La méthode (le cœur)

### 2.1 Courbe de survie — commande `courbe_survie`
`fedow_core/management/commands/courbe_survie.py` (lecture seule, à lancer à la main) :
1. Parcourt toutes les transactions FED dans l'ordre du temps.
2. **FIFO par wallet user** : chaque dépense consomme l'argent le plus ancien → chaque euro
   chargé reçoit une *durée de vie* (« dépensé à X mois » ou « encore vivant à Y mois »).
3. **Kaplan-Meier discret** : taux de dépense par mois d'âge, en ne comptant à l'âge `a` que
   l'argent qui a *eu le temps* d'atteindre `a` (gère la censure → **neutralise le biais de
   saisonnalité** : le pic 6-12 mois du snapshot était un festival, pas un taux de survie).
4. Écrit `database/courbe_survie.json` :
   - `survie` : `[{age_mois, part_restante}]` (S(âge), de 0 à l'horizon, défaut 24) ;
   - `stock_par_age` : `[{age_mois, montant_centimes, nb_cartes}]` (stock **actuel** par âge
     depuis recharge — sert à projeter ; `nb_cartes` sert au mode « 1 €/mois ») ;
   - totaux (`total_refill_centimes`, `total_suivi_centimes`, `nb_wallets_avec_solde`).
   - **FED uniquement** (`Asset.STRIPE_FED_FIAT`).

### 2.2 Projection (client, `fedow_simulateur.js`)
Pour chaque tranche `(âge a, montant m, cartes c)` du `stock_par_age` :
- devient fondable au mois `t = max(0, seuil − a)` ;
- part encore présente au seuil = `survie(seuil)/survie(a)` (1 si `a ≥ seuil`) ;
- **« tout d'un coup »** : `m × part` ajouté à la barre du mois `t` ;
- **« 1 €/mois »** : `c × montant_fixe` par mois à partir de `t`, jusqu'à épuisement (étalé).

**Zone certaine [0, +seuil] uniquement** : tout repose sur de l'argent déjà encaissé. Au-delà
de `+seuil`, il faudrait supposer les recharges futures → **non affiché** (choix du mainteneur).

### 2.3 Frontière certain / spéculatif (data-science)
Une barre au mois `+t` provient de l'argent qui a **aujourd'hui** l'âge `seuil − t`. Donc :
`t ≤ seuil` → argent déjà sur les cartes → **certain** ; `t > seuil` → recharge future → spéculatif.
→ On a `seuil` mois de **visibilité fiable** d'un coup, puis bascule. En relançant la commande
chaque mois, la fenêtre glisse et les barres lointaines se figent (auto-affinage).

## 3. La carte « Recette de fonte attendue »

`asset/asset_transactions.html`, remplace l'ancien simulateur **et** la projection run-off
(les deux supprimés). Graphe en **barres**, 2 séries (« tout d'un coup » orange / « 1 €/mois »
bleu). Contrôles : **seuil** (décale les barres + change le taux capté), **montant fixe**,
**fenêtre d'affichage**. KPI : total par mode, *déjà fondable* (barre d'aujourd'hui), *cartes
concernées*. Vue : `_charge_courbe_survie(asset)` lit le JSON (aucune requête base), caché.
Dégradation propre si pas de JSON (monnaies locales → message).

## 4. Faits prod utiles

- Survie FED : **1 mois ≈ 11 %**, 3 mois ≈ 8,6 %, 6 mois ≈ 8,0 %, **12 mois ≈ 6,8 %**, 24 mois ≈ 6,3 %.
  → ~89 % dépensé le 1er mois, le reste « colle ».
- Recharges FED : 2024 = 12 250 (démarrage août), **2025 = 165 943** (seule année complète,
  dont **août 2025 = 91 026 ≈ 55 % de l'année**), 2026 partiel. **Forte saisonnalité festival.**
- Revenu de fonte récurrent ≈ volume annuel glissant (~204 k) × ~6,6 % ≈ **~13 300 FED/an**.
- Pourquoi le « dormant ciblé » à seuil 14 mois est petit (~1 250 FED) : le réseau est **jeune**,
  le gros du dormant (festival août 2025, ~9 mois) n'a pas encore 14 mois. Baisser le seuil le révèle.

## 5. Idées non faites / suite

- **Zone spéculative (> +seuil)** : barres pâles basées sur une hypothèse de recharges futures
  (ex : rejouer l'année écoulée, ou curseur de croissance). **Écartée** pour l'instant
  (mainteneur : « on n'affiche que les données certaines »).
- **Monnaies locales (`TLF`)** : la commande ne calcule que FED ; l'étendre donnerait la
  projection sur les monnaies locales (sinon la carte affiche un message « indisponible »).
- **Seuil par défaut** : 14 mois (trop haut pour un réseau jeune ? un défaut plus bas, ~6 mois,
  montrerait tout de suite quelque chose — non tranché).
- **Automatisation** de la commande (cron/Celery) au lieu du lancement manuel.
- Le mode « 1 €/mois » utilise `nb_cartes` = **nb de tranches FIFO** (proxy du nb de cartes) :
  léger sur-comptage si une carte a plusieurs tranches — acceptable, à raffiner si besoin.

## 6. Infra / déploiement

- Rafraîchir la courbe : `docker exec fedow_django poetry run python manage.py courbe_survie`
  (visible immédiatement via le bind-mount ; pas besoin de reload pour la commande elle-même).
- Modif **JS** → `collectstatic` ; modif **template / vue / settings** → reload gunicorn
  (`docker exec fedow_django pkill -HUP gunicorn`).
- **`django_browser_reload` désactivé** (middleware commenté dans `settings.py`) : la page ne se
  recharge plus seule. Réversible (décommenter).
- Vérif : `Client.force_login(superuser)` + `HTTP_HOST=fedow.tibillet.localhost`, ou Chrome sur
  `https://fedow.tibillet.localhost/dashboard/asset/<uuid-FED>/`.
