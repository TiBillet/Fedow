# Plan d'implémentation — Spec 2 : Vue réseau globale

> **Méthode** : exécution inline. **Règles** : AUCUN commit auto, AUCUNE écriture DB (lecture seule), zéro N+1 (tout en agrégats), cache memcached.

**Goal** : remplacer la page d'accueil `index` (compteurs bruts) par une vue d'ensemble réseau pour l'admin.

**Principe anti-mélange d'unités** : on ne somme jamais des monnaies différentes. Sommes monétaires uniquement **par asset** (Module A) ou sur la **seule FED** (Module D). Classements/pouls en **nombre de transactions** (Module B, C).

---

## Module A — Masse monétaire par monnaie (`_masse_par_monnaie`)
4 agrégats groupés par asset + 1 lecture des assets (5 requêtes, O(1)) :
- circulation : `Token.filter(asset__archive=False, wallet__place__isnull=True).values('asset').annotate(Sum('value'))`
- lieux : idem `wallet__place__isnull=False`
- banque : `Transaction.filter(action=DEPOSIT).values('asset').annotate(Sum('amount'))`
- créé : `Transaction.filter(action=CREATION).values('asset').annotate(Sum('amount'))`
- jointure en Python sur `Asset.objects.filter(archive=False)`, regroupé par catégorie (`Asset.CATEGORIES`).
- chaque ligne porte son `unite` (FID → "pts", sinon `currency_code`). Pas de total cross-devises.

## Module B — Top lieux (`_top_lieux`, limite 10)
2 agrégats (2 requêtes) :
- nb transactions entrantes par lieu : `Transaction.exclude(FIRST).filter(receiver__place__isnull=False).values('receiver__place__uuid','receiver__place__name').annotate(Count, Sum('amount'))`
- solde détenu (toutes monnaies, **indicatif**) : `Token.filter(wallet__place__isnull=False).values('wallet__place__...').annotate(Sum('value'))`
- fusion par uuid lieu, tri par **nb de transactions** desc, top 10. Le solde est libellé « toutes monnaies » (indicatif).

## Module C — Activité récente réseau (`_activite_reseau`)
2 requêtes :
- pouls : nb de transactions par mois `Transaction.exclude(FIRST).annotate(TruncMonth).values('mois').annotate(Count)` → graphe Chart.js (nombre, pas montant → agnostique à l'unité).
- dernières transactions : `Transaction.exclude(FIRST).select_related('asset','sender','sender__place','receiver','receiver__place').order_by('-datetime')[:15]`.

## Module D — Dormance FED (`_dormance_fed`)
- `fed = Asset.objects.filter(category=Asset.STRIPE_FED_FIAT).first()`
- si `fed` : réutilise `_calcul_monnaie_fondante(fed)` (total + courbe). Lien « Simuler la fonte » → page asset FED (Spec 3).

## Orchestration (`get_dashboard_reseau`, cache 5 min)
Renvoie `{masse, top_lieux, activite, dormance_fed, fed_uuid}`. ~11 requêtes constantes.

## `index(request)`
Remplacer le contexte par `get_dashboard_reseau()` + compteurs simples (counts).

## Fichiers
| Fichier | Changement |
|---|---|
| `fedow_dashboard/views.py` | helpers réseau + `get_dashboard_reseau` + `index` réécrit |
| `fedow_dashboard/templates/index/index.html` | refonte 4 modules |
| `fedow_dashboard/static/js/fedow_charts.js` | graphe pouls réseau (`#chart-volume-reseau`) |

## Vérif (lecture seule)
- `manage.py check` ; reload gunicorn.
- shell `CaptureQueriesContext` sur `get_dashboard_reseau` → nb requêtes constant (pas de N+1).
- curl `/dashboard/` → HTTP 200, 4 modules présents.
