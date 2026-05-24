# Session dashboard Fedow — récap & suite (2026-05-24)

> Document de reprise pour la **prochaine session** (qui sera une compaction de celle-ci).
> Il doit se suffire à lui-même. Voir aussi les specs/plans du même dossier et `CHANGELOG.md`.

## 0. Règles non négociables (rappel)

- **LECTURE SEULE en base.** Aucune écriture, aucune migration. Tout est agrégation `SELECT`
  + calcul front. **Reconfirmer « lecture seule » avant chaque modif de code.**
- **Aucun commit.** Le mainteneur committe lui-même. **Jamais de co-authored.**
- **Zéro N+1**, base fragile → agrégats + cache. Vérifié : requêtes constantes même sur
  42 938 tx (FED).

## 1. État final — ce qui est construit & vérifié

Dashboard Fedow (`fedow_dashboard/`) enrichi, **vérifié sur la DB de prod** (rendu via
`Client.force_login` + curl interne, HTTP 200, marqueurs présents). Détail dans `CHANGELOG.md`.

**Page asset** (`asset/asset_transactions.html`), dans l'ordre :
KPI → cycle de vie (barre CSS) → monnaie fondante (Chart.js) → **breakage (rétention)** →
**simulateur de fonte** → **projection à 12 mois (run-off)** → **moyennes par portefeuille** →
graphe temporel → dernières transactions (repliables).

**Page réseau** (`index/index.html`) : masse par monnaie (par catégorie, couleurs, FED en
premier, hors SUB/BDG) · top lieux · pouls réseau · dormance FED · compteurs.

**Transverse** : auth `@staff_member_required` (asset/place ; home publique) · thème clair
par défaut + `sessionStorage` · unités par catégorie (`unite_asset`) · Chart.js vendorisé.

## 2. Faits data PROD (utiles pour reprendre)

- DB = **prod montée en local** (bind-mount `../Fedow/database`). **Les UUID d'assets diffèrent
  des démos** → piocher dynamiquement (`Asset.objects.filter(...).first()`), ne jamais hardcoder.
- 36 709 wallets (36 321 user), 43 882 cartes. Activité **événementielle/saisonnière**
  (pics de festivals : août 2025 = 91 025 FED chargés ; creux ~2 000).
- **FED** (`category=STRIPE_FED_FIAT`, ~42 938 tx) : 7 370 cartes ont eu du FED →
  **2 485 avec solde > 0**, **4 885 vidées**. 28 951 wallets n'ont jamais eu de FED.
- **Solde FED total sur cartes** : 17 952 FED. **Total chargé** : 223 877 FED →
  **taux de breakage ≈ 8 %**. Snapshot par âge : le pic « 6-12 mois » (7 238 FED) = le
  **festival d'août 2025** (⚠️ saisonnalité, PAS une courbe de survie — voir §4).
- Solde moyen FED : 7,22 (détenteurs actuels) vs 2,44 (par carte distribuée, vidées incluses).

## 3. Infra / déploiement (IMPORTANT)

- Fedow tourne via le compose **Lespass** `/home/jonas/TiBillet/dev/Lespass/docker-compose-laboutik-V1.yml`
  (image `tibillet/fedow:latest`, gunicorn 5 workers `start.sh`, Traefik `fedow.tibillet.localhost`).
- Ajouté à ce compose : bind-mount `../Fedow:/home/fedow/Fedow` (service `fedow_django`) +
  volume statique partagé `../Fedow/www:/www` (service `fedow_nginx`).
- **Templates CACHÉS** (`cached.Loader`) → modif template OU vue Python = **reload gunicorn**
  (`docker exec fedow_django pkill -HUP gunicorn`). Modif **JS/CSS** = `collectstatic`
  (`docker exec fedow_django poetry run python manage.py collectstatic --noinput`), servi par nginx.
- `DEBUG=1` actuellement → `django_browser_reload` actif (auto-reload de page) ; le mainteneur
  le laisse tel quel. Traefik régénère parfois son certif auto-signé au recreate → ré-accepter
  dans le navigateur (NE PAS contourner côté Claude).
- Vérif sandbox : on n'atteint pas Traefik (`127.0.0.1:443`) ; tester les maillons en interne
  (curl dans les conteneurs, `Client.force_login` pour les vues protégées avec
  `HTTP_HOST=fedow.tibillet.localhost`).

## 4. ✅ RÉSOLU — fusionner « simulateur » et « projection 12 mois »

> **Tranché le 2026-05-24** → voir **`2026-05-24-projection-fonte.md`**. On a fusionné les deux
> cartes, puis pivoté vers une **projection de la recette de fonte** (graphe en barres) alimentée
> par une vraie **courbe de survie** (commande `courbe_survie` → `database/courbe_survie.json`).
> On n'affiche que la **zone certaine** (jusqu'au seuil), basée sur l'argent déjà rechargé.
> Le texte ci-dessous est conservé pour l'historique de la réflexion.

C'est le **sujet principal de la prochaine session**. Aujourd'hui ce sont **deux cartes séparées** :

- **Simulateur de fonte** = *what-if de politique* : « si j'applique une fonte (montant fixe
  /mois OU tout prendre) sur le stock dormant actuel, voilà comment il se résorbe ». Mécanique
  exacte sur `wallets_dormants`. Curseur seuil + horizon. Courbe = solde dormant restant.
- **Projection à 12 mois (run-off)** = *prédiction* : « sans rien faire, voilà comment le stock
  actuel évolue ». Aujourd'hui = **heuristique grossière indicative** (> 12 mois = breakage
  permanent, le reste linéaire sur 12 mois). FED : ~16 341 sortira, ~1 611 restera.

**Objectif à discuter** : les fusionner en **une seule vue** qui compare *« sans intervention »*
(projection naturelle) **vs** *« avec fonte »* (what-if), idéalement sur le même graphe (2 courbes)
ou un panneau unifié.

**Points data-science à garder en tête pour la fusion :**
1. **Le snapshot par âge ≠ courbe de survie.** La forme par âge est déformée par la
   saisonnalité des chargements (le pic 6-12 mois = un festival passé, pas un taux de survie).
   → On **ne peut pas** rouler le snapshot tel quel pour prévoir de façon fiable.
2. **La projection fiable = run-off du stock ACTUEL** (connu) via une **courbe de survie par
   âge** — sans deviner les festivals futurs (l'incertitude majeure est ainsi écartée).
3. La courbe de survie fiable demande un **pass offline sur la chaîne** (cohortes : balance par
   âge depuis le 1er chargement), mis en cache. **Différé** : on a choisi une heuristique d'abord.
   Quand on voudra du calibré : tâche Celery / commande de gestion + bande de confiance.
4. **Pour une fusion propre, simulateur ET projection devraient partager le même moteur de
   décroissance** : la courbe de survie (réelle) → la projection naturelle ET le what-if de fonte
   deviennent cohérents et comparables sur le même axe.

**Questions ouvertes pour reprendre la discussion :**
- Une carte unique avec 2 courbes (« naturel estimé » + « avec fonte ») ? Aligner l'horizon
  (run-off fixe 12 mois vs horizon réglable du simulateur).
- Sémantique de « ce qu'on touchera » : breakage *gardé* (jamais réclamé) vs argent *remboursé*
  (sorti). À clarifier dans les libellés.
- Garde-t-on l'heuristique en attendant la survie par cohortes, ou on attaque directement le
  moteur de survie pour fiabiliser la fusion ?

## 5. Roadmap / pistes non faites

- **Moteur de survie par cohortes** (offline, caché) → fiabilise projection + fusion (§4).
- Prévision avec **calendrier de festivals connu** (chargement attendu × taux de breakage 8 %).
- Breakage **comparé par monnaie locale** (Houblon, Pils, RaffTou… taux peut-être différents).
- Autres idées évoquées : histogramme de répartition des soldes, top portefeuilles anonymisés,
  taux de remboursement.
- Page asset **dense** → envisager des onglets si besoin.

## 6. Fichiers & specs

- Code : voir tableau « Fichiers modifiés » du `CHANGELOG.md`.
- Specs/plans : `TECH_DOC/SESSIONS/dashboard/` (spec-1/2/3 + plans).
- Mémoire projet Claude : `fedow-dashboard-chantier`, `fedow-moteur`, `fedow-nature`,
  `specs-location`.
