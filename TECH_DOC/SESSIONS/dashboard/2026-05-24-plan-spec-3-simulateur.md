# Plan d'implémentation — Spec 3 : Simulateur de fonte

> **Règles** : AUCUN commit auto, AUCUNE écriture DB. **Spec 100 % template + JS** : la donnée
> `wallets_dormants` (liste anonymisée `[âge_jours, solde_centimes]`) est déjà calculée par
> `_calcul_monnaie_fondante` (Spec 1) et déjà sérialisée côté client dans le `json_script`
> `#data-monnaie-fondante`. Aucune nouvelle requête serveur.

**Goal** : un simulateur « et si ? » dans la section monnaie fondante de la page asset.

**Calcul** : 100 % côté client, recalculé en direct sur mouvement des curseurs (zéro requête).

---

## Aucune modification serveur nécessaire
`monnaie_fondante_json` (déjà au contexte) contient `wallets_dormants` et `currency_code`, et
le template asset dumpe déjà `{{ monnaie_fondante_json|json_script:"data-monnaie-fondante" }}`.
Le simulateur lit cette balise. Rien à changer dans `views.py`.

## Task 1 — Section UI dans le template
**Files :** Modify `fedow_dashboard/templates/asset/asset_transactions.html`

Ajouter une carte `data-testid="asset-simulateur"` après la carte monnaie fondante :
- **Contrôles** : mode (`select` : pourcent / fixe / tout), seuil d'inactivité (`range` 1–36 mois),
  taux %/mois (`range`, visible si mode=pourcent), montant fixe/mois (`number`, visible si mode=fixe),
  horizon de projection (`range` 1–36 mois, défaut 12).
- **Sorties** : recette ce mois, recette sur horizon, volume concerné, nb wallets touchés, +
  `<canvas id="chart-simulateur">` (courbe de fonte cumulée).
- État vide si `monnaie_fondante_json.wallets_dormants` est vide.
- Charger `fedow_simulateur.js` dans le bloc `extra_js` (après `fedow_charts.js`).

## Task 2 — Logique client
**Files :** Create `fedow_dashboard/static/js/fedow_simulateur.js`

- Lit `#data-monnaie-fondante` (`.wallets_dormants`, `.currency_code`).
- `calculer(mode, seuilJours, taux, montantCentimes, horizon)` :
  - `eligibles` = soldes des wallets d'âge ≥ seuil ; `volume` = somme ; `nbWallets` = compte.
  - **pourcent** : agrégat décroissant — chaque mois `melt = D*taux ; D -= melt`.
  - **fixe** : par wallet, chaque mois `min(montant, solde restant)` ; décrémente.
  - **tout** : `melt[0] = volume`, reste 0.
  - renvoie série mensuelle + cumulée, recette mois 1, recette cumulée.
- Met à jour les sorties (formatage `toLocaleString('fr-FR')`) et le graphe (crée/maj une instance Chart.js).
- Écouteurs `input` sur tous les contrôles → recalcul instantané. Bascule pourcent/fixe selon le mode.

## Vérif (lecture seule)
- `manage.py check` ; reload gunicorn (pas nécessaire car template/JS à chaud, mais inoffensif).
- Curl page asset (FED + TLF) → HTTP 200, présence `asset-simulateur`, `chart-simulateur`, `fedow_simulateur.js`.
- Navigateur : déplacer les curseurs → sorties qui changent, **aucune requête réseau** (onglet Network).
- Validation math : 30 000 @ 2 % → 600 le 1er mois (jeu de test mental).
