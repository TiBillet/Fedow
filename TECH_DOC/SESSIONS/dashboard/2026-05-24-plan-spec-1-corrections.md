# Plan d'implémentation — Spec 1 : Corrections & robustesse

> **Méthode** : exécution inline, tâche par tâche. Cases à cocher pour le suivi.
> **Règles projet (override)** : AUCUN commit automatique (le mainteneur commit). AUCUNE écriture DB (lecture seule stricte). Pas de TDD lourde sur de l'affichage → vérification par shell read-only + curl + `manage.py check`.

**Goal** : corriger les défauts d'hygiène/robustesse de la page asset (`asset_transactions.html`) et préparer la donnée du simulateur (Spec 3).

**Architecture** : helpers de calcul en lecture seule dans `fedow_dashboard/views.py`, mis en cache ; affichage dans le template + `fedow_charts.js`.

**Rappel infra** : modifs Python → `docker exec fedow_django pkill -HUP gunicorn`. Modifs template/JS → à chaud.

---

## Décisions verrouillées (pour lever toute ambiguïté)

- **Graphe temporel** = flux de **circulation uniquement**. On exclut `FIRST` (genèse) **et** `CREATION` (frappe monétaire, déjà comptée dans le KPI « créé » du cycle de vie). Évite le double-compte des recharges (une recharge = CREATION + REFILL). Actions gardées : `REFILL`, `SALE`, `QRCODE_SALE`, `SUBSCRIBE`, `REFUND`, `DEPOSIT`, `TRANSFER`, `FUSION`, `VOID`.
- **Unité** : on affiche toujours `asset.currency_code` comme libellé d'unité (ex. « H » pour la monnaie temps). Pas de « € » codé en dur. Valeur = `value/100` (convention centimes du modèle).
- **verify_hash** : on retire la re-vérification par ligne (intégrité garantie à l'écriture + Sentry). On garde l'affichage du hash court (8 car.) sans recalcul.

---

## Task 1 — `_calcul_temporel` : exclure FIRST+CREATION, combler les mois vides

**Files :** Modify `fedow_dashboard/views.py` (`_calcul_temporel`)

- [ ] **Step 1 — Remplacer la requête et la construction des mois**

```python
def _calcul_temporel(asset):
    """
    Agrège les flux de CIRCULATION par mois et par type d'action (montants en euros).
    / Aggregates CIRCULATION flows by month and action type.

    On exclut FIRST (genèse) et CREATION (frappe monétaire, déjà comptée dans le cycle
    de vie) pour ne pas gonfler le volume : une recharge = CREATION + REFILL.
    Une seule requête agrégée (TruncMonth + Sum + Count), donc pas de N+1.
    """
    actions_circulation_exclues = [Transaction.FIRST, Transaction.CREATION]

    lignes = (asset.transactions
              .exclude(action__in=actions_circulation_exclues)
              .annotate(mois=TruncMonth('datetime'))
              .values('mois', 'action')
              .annotate(nombre=Count('uuid'), total=Sum('amount'))
              .order_by('mois'))

    labels_action = dict(Transaction.TYPE_ACTION)

    # On construit la liste continue des mois (du premier au dernier), sans trou.
    # / Build the continuous list of months (first to last), no gap.
    mois_presents = sorted({ligne['mois'] for ligne in lignes if ligne['mois']})
    mois_ordonnes = []
    if mois_presents:
        curseur = mois_presents[0].replace(day=1)
        dernier = mois_presents[-1].replace(day=1)
        while curseur <= dernier:
            mois_ordonnes.append(curseur.strftime('%Y-%m'))
            # Mois suivant (gestion du passage d'année).
            # / Next month (year rollover).
            if curseur.month == 12:
                curseur = curseur.replace(year=curseur.year + 1, month=1)
            else:
                curseur = curseur.replace(month=curseur.month + 1)

    montant_par_action = {}  # action -> { "2026-05": montant_euros }
    for ligne in lignes:
        if not ligne['mois']:
            continue
        mois_str = ligne['mois'].strftime('%Y-%m')
        action = ligne['action']
        montant_par_action.setdefault(action, {})[mois_str] = round((ligne['total'] or 0) / 100, 2)

    datasets = []
    for action, montants in montant_par_action.items():
        datasets.append({
            'label': str(labels_action.get(action, action)),
            'data': [montants.get(mois, 0) for mois in mois_ordonnes],
            'backgroundColor': COULEURS_ACTION.get(action, "#8898aa"),
        })

    return {
        'labels': mois_ordonnes,
        'datasets': datasets,
        'vide': len(mois_ordonnes) == 0,
    }
```

- [ ] **Step 2 — Vérif read-only** : `docker exec fedow_django pkill -HUP gunicorn` puis shell : confirmer qu'aucun dataset « Premier bloc » / « Creation monétaire » n'apparaît et que `labels` est continu.

---

## Task 2 — `_calcul_monnaie_fondante` : O(wallets) + liste anonymisée (pour Spec 3)

**Files :** Modify `fedow_dashboard/views.py` (`_calcul_monnaie_fondante`)

- [ ] **Step 1 — Remplacer la reconstruction des dernières activités par 2 GROUP BY**

```python
def _calcul_monnaie_fondante(asset):
    """
    Monnaie fondante : tokens dormants sur les wallets inactifs (LECTURE SEULE, sans N+1).

    Optim : la date de dernière activité par wallet est obtenue par 2 requêtes agrégées
    (Max(datetime) par sender, puis par receiver), donc O(wallets) et non O(transactions).
    "Inactif" = dernière tx en émetteur OU receveur (une recharge sans dépense = actif : voulu).
    """
    from django.db.models import Max

    maintenant = timezone.now()
    tx = Transaction.objects.filter(asset=asset).exclude(action=Transaction.FIRST)

    derniere_activite_par_wallet = {}
    for row in tx.values('sender').annotate(last=Max('datetime')):
        derniere_activite_par_wallet[row['sender']] = row['last']
    for row in tx.values('receiver').annotate(last=Max('datetime')):
        wallet_id = row['receiver']
        ancienne = derniere_activite_par_wallet.get(wallet_id)
        if ancienne is None or row['last'] > ancienne:
            derniere_activite_par_wallet[wallet_id] = row['last']

    # Soldes positifs hors lieux et hors wallet primaire.
    # / Positive balances excluding places and the primary wallet.
    tokens = (Token.objects
              .filter(asset=asset, value__gt=0,
                      wallet__place__isnull=True,
                      wallet__primary__isnull=True)
              .values_list('wallet_id', 'value'))

    # Liste anonymisée (âge en jours, solde en centimes) — réutilisée par le simulateur (Spec 3).
    # / Anonymized (age in days, balance in cents) list — reused by the simulator (Spec 3).
    wallets_dormants = []
    for wallet_id, value in tokens:
        derniere = derniere_activite_par_wallet.get(wallet_id)
        if derniere is None:
            continue
        age_jours = (maintenant - derniere).days
        wallets_dormants.append((age_jours, value))

    labels = []
    data = []
    for jours, label in SEUILS_INACTIVITE:
        total_centimes = sum(value for age_jours, value in wallets_dormants if age_jours >= jours)
        labels.append(label)
        data.append(round(total_centimes / 100, 2))

    return {
        'labels': labels,
        'data': data,
        'currency_code': asset.currency_code,
        'total_max': max(data) if data else 0,
        # Pour le simulateur (Spec 3) : anonymisé, sans user ni uuid.
        # / For the simulator (Spec 3): anonymized, no user or uuid.
        'wallets_dormants': wallets_dormants,
    }
```

- [ ] **Step 2 — Vérif read-only (compte de requêtes)** : via `CaptureQueriesContext`, confirmer un nombre de requêtes **constant** (≈3 pour cette fonction) indépendant du nombre de transactions.

---

## Task 3 — Helper d'unité (libellé selon la catégorie)

**Files :** Modify `fedow_dashboard/templatetags/fedow_dashboard_tags.py`

- [ ] **Step 1 — Ajouter un filtre `unite_asset`** (libellé d'unité d'un asset)

```python
from fedow_core.models import Asset

@register.filter
def unite_asset(asset):
    """
    Renvoie le libellé d'unité à afficher pour un asset.
    / Returns the unit label to display for an asset.

    Monnaie temps -> code devise (ex "H" pour heures). Fidélité -> "pts".
    Sinon -> code devise (ex "EUR", "MLC"...).
    """
    if asset.category == Asset.FIDELITY:
        return "pts"
    return (asset.currency_code or "").upper()
```

- [ ] **Step 2** : (le filtre `dround` reste inchangé pour la valeur numérique `value/100`.)

---

## Task 4 — Template : intcomma, chiffres tabulaires, libellés d'unité, retrait re-vérif hash

**Files :** Modify `fedow_dashboard/templates/asset/asset_transactions.html`

- [ ] **Step 1 — Charger `humanize`** (déjà chargé : `{% load static humanize i18n fedow_dashboard_tags %}`). Ajouter le CSS chiffres tabulaires dans le bloc `extra_css` :

```css
.kpi-value, .table td, .cycle-bar + .row strong { font-variant-numeric: tabular-nums; }
```

- [ ] **Step 2 — Formater les KPI avec `intcomma` + unité** (exemple sur une carte, à répliquer sur les 4) :

```html
<p class="kpi-value mb-0" data-testid="kpi-cree">
    {{ cycle_de_vie.cree_euros | floatformat:2 | intcomma }}
    <span class="text-sm text-secondary">{{ asset | unite_asset }}</span>
</p>
```

- [ ] **Step 3 — Retirer la re-vérification du hash dans le tableau** : remplacer le bloc `{% if transaction.verify_hash %}…` par l'affichage du hash court seul :

```html
<td>
    <p class="text-xs font-weight-bold mb-0">{{ transaction.hash | slice:":8" }}</p>
</td>
```

- [ ] **Step 4** : remplacer les libellés `{{ asset.currency_code | upper }}` par `{{ asset | unite_asset }}` aux endroits d'affichage de montants (KPI, cycle de vie).

---

## Task 5 — Vérification globale (LECTURE SEULE)

- [ ] **Step 1** : `docker exec fedow_django poetry run python manage.py check`  → 0 issue.
- [ ] **Step 2** : `docker exec fedow_django pkill -HUP gunicorn` (recharger le code Python).
- [ ] **Step 3 — Shell read-only** : exécuter les 3 `_calcul_*` sous `CaptureQueriesContext` sur un asset `TLF`, `FED`, `TIM` → nombre de requêtes constant ; vérifier `labels` temporels continus + absence de FIRST/CREATION ; unité « H » pour le TIM.
- [ ] **Step 4 — Curl** (`-H 'Host: fedow.tibillet.localhost'`) sur une page asset TLF, FED, TIM → HTTP 200, présence des sections, nombres avec séparateurs de milliers, plus de colonne « valide/invalide ».
- [ ] **Step 5 — STOP** : présenter le diff au mainteneur + proposer un message de commit. **Ne pas committer.**

---

## Self-review (couverture Spec 1)

| Item Spec 1 | Task |
|---|---|
| 1. Exclure FIRST | Task 1 |
| 2. Séparer CREATION/REFILL (pas de double-compte) | Task 1 (CREATION hors graphe volume) |
| 3. Mois vides comblés | Task 1 |
| 4. Unités par catégorie | Task 3 + Task 4 |
| 5. Formatage lisible | Task 4 |
| 6. Optim `_calcul_monnaie_fondante` O(wallets) | Task 2 |
| 7. Retirer verify_hash du tableau | Task 4 |
| 8. Cache (pas de sur-ingénierie) | inchangé, OK |

Aucun placeholder. Donnée `wallets_dormants` (Task 2) consommée plus tard par Spec 3.
