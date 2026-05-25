import json
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.core.cache import cache
from django.db.models import Sum, Count, Max
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from django.views.decorators.cache import cache_page
from django.contrib.admin.views.decorators import staff_member_required

from fedow_core.models import Asset, Place, Wallet, Card, Federation, Configuration, Transaction, Token
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TABLEAU DE BORD ASSET — calculs en LECTURE SEULE, mis en cache
# / ASSET DASHBOARD — READ-ONLY computations, cached
#
# LOCALISATION : fedow_dashboard/views.py
#
# Ces fonctions ne font QUE lire la base (agrégations). Elles n'écrivent rien.
# Tout est mis en cache (memcached) pour soulager la base de production qui est fragile.
# / These functions only READ the database (aggregations). They write nothing.
#   Everything is cached (memcached) to relieve the fragile production database.
# ---------------------------------------------------------------------------

# Seuils d'inactivité pour la "monnaie fondante", du plus long au plus court.
# Un seuil long contient moins de wallets : la courbe cumulée monte vers la droite.
# / Inactivity thresholds for "melting money", longest to shortest.
SEUILS_INACTIVITE = [
    (730, "+2 ans"),
    (545, "+18 mois"),
    (365, "+1 an"),
    (180, "+6 mois"),
    (90, "+3 mois"),
    (30, "+1 mois"),
]

# Couleur de chaque type d'action pour le graphe temporel (lisible en thème clair et sombre).
# / Color per action type for the time chart (readable in light and dark themes).
COULEURS_ACTION = {
    Transaction.CREATION: "#2dce89",     # vert : création monétaire / green: money creation
    Transaction.REFILL: "#11cdef",       # cyan : recharge / refill
    Transaction.SALE: "#5e72e4",         # bleu : vente / sale
    Transaction.QRCODE_SALE: "#825ee4",  # violet : vente QrCode/NFC
    Transaction.SUBSCRIBE: "#fb6340",    # orange : adhésion / subscription
    Transaction.REFUND: "#f5365c",       # rouge : remboursement / refund
    Transaction.DEPOSIT: "#ffd600",      # jaune : remise en banque / bank deposit
    Transaction.TRANSFER: "#8898aa",     # gris : transfert / transfer
    Transaction.FUSION: "#adb5bd",
    Transaction.BADGE: "#344767",
    Transaction.VOID: "#ced4da",
    Transaction.FIRST: "#dee2e6",
}


def _calcul_cycle_de_vie(asset):
    """
    Construit le "cycle de vie" de la monnaie d'un asset.
    / Builds the money "lifecycle" of an asset.

    Les soldes sont stockés en centimes ; on les convertit en euros pour l'affichage.
    / Balances are stored in cents; converted to euros for display.
    """
    en_circulation_centimes = asset.total_in_wallet_not_place()
    dans_les_lieux_centimes = asset.total_in_place()
    remis_en_banque_centimes = asset.total_bank_deposit()

    # Monnaie créée = somme des créations monétaires (action CREATION).
    # / Money minted = sum of monetary creations (CREATION action).
    cree_centimes = (asset.transactions
                     .filter(action=Transaction.CREATION)
                     .aggregate(total=Sum('amount'))['total'] or 0)

    # Total des tokens existant aujourd'hui (en circulation + dans les lieux).
    # / Total tokens existing today (in circulation + in places).
    total_actuel_centimes = en_circulation_centimes + dans_les_lieux_centimes

    # Pourcentages pour la barre empilée (largeur CSS). On évite la division par zéro.
    # / Percentages for the stacked bar (CSS width). Avoid division by zero.
    if total_actuel_centimes > 0:
        pct_circulation = round(en_circulation_centimes / total_actuel_centimes * 100, 1)
        pct_lieux = round(dans_les_lieux_centimes / total_actuel_centimes * 100, 1)
    else:
        pct_circulation = 0
        pct_lieux = 0

    return {
        'cree_euros': round(cree_centimes / 100, 2),
        'en_circulation_euros': round(en_circulation_centimes / 100, 2),
        'dans_les_lieux_euros': round(dans_les_lieux_centimes / 100, 2),
        'remis_en_banque_euros': round(remis_en_banque_centimes / 100, 2),
        'total_actuel_euros': round(total_actuel_centimes / 100, 2),
        'pct_circulation': pct_circulation,
        'pct_lieux': pct_lieux,
    }


def _calcul_monnaie_fondante(asset):
    """
    Calcule la "monnaie fondante" : combien de tokens dorment sur les wallets inactifs.
    / Computes "melting money": how many tokens sleep on inactive wallets.

    Optim : la date de dernière activité par wallet est obtenue par 2 requêtes agrégées
    (Max(datetime) par sender, puis par receiver), donc O(wallets) et non O(transactions).
    "Inactif" = dernière tx en émetteur OU receveur (une recharge sans dépense = actif : voulu).

    / Optim: last activity date per wallet via 2 aggregated queries (Max by sender, by receiver),
      so O(wallets) not O(transactions). "Inactive" = last tx as sender OR receiver.
    """
    maintenant = timezone.now()
    tx = Transaction.objects.filter(asset=asset).exclude(action=Transaction.FIRST)

    # Date de dernière activité par wallet, via 2 GROUP BY fusionnés (O(wallets)).
    # / Last activity date per wallet, via 2 merged GROUP BY (O(wallets)).
    derniere_activite_par_wallet = {}
    for row in tx.values('sender').annotate(last=Max('datetime')):
        derniere_activite_par_wallet[row['sender']] = row['last']
    for row in tx.values('receiver').annotate(last=Max('datetime')):
        wallet_id = row['receiver']
        ancienne = derniere_activite_par_wallet.get(wallet_id)
        if ancienne is None or row['last'] > ancienne:
            derniere_activite_par_wallet[wallet_id] = row['last']

    # Soldes positifs, hors lieux (place) et hors wallet primaire.
    # / Positive balances, excluding places and the primary wallet.
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

    # Pour chaque seuil : somme cumulée des wallets inactifs depuis au moins ce seuil.
    # / For each threshold: cumulative sum of wallets inactive for at least that long.
    labels = []
    data = []
    for jours, label in SEUILS_INACTIVITE:
        total_centimes = sum(value for age_jours, value in wallets_dormants if age_jours >= jours)
        labels.append(label)
        data.append(round(total_centimes / 100, 2))

    # Total dépensé par les users (ventes) — pour la « dépense moyenne / portefeuille ».
    # / Total spent by users (sales) — for the per-wallet "average spend".
    depense_totale_centimes = (tx.filter(action__in=[Transaction.SALE, Transaction.QRCODE_SALE])
                               .aggregate(total=Sum('amount'))['total'] or 0)

    # Nb de portefeuilles user ayant eu l'asset mais vidés (solde 0) — pour les moyennes.
    # / Count of user wallets that held the asset but are now empty — for the averages.
    nb_vides = (Token.objects
                .filter(asset=asset, value=0, wallet__place__isnull=True, wallet__primary__isnull=True)
                .count())

    # Total chargé sur les cartes (recharges) — pour le taux de breakage (rétention).
    # / Total loaded onto cards (refills) — for the breakage (retention) rate.
    total_charge_centimes = (tx.filter(action=Transaction.REFILL)
                             .aggregate(total=Sum('amount'))['total'] or 0)

    return {
        'labels': labels,
        'data': data,
        'currency_code': asset.currency_code,
        # Sert à l'affichage de l'état vide (rien ne dort).
        # / Used to render the empty state (nothing sleeping).
        'total_max': max(data) if data else 0,
        # Anonymisé (sans user ni uuid) — réutilisé par le simulateur, les moyennes ET le breakage (JS).
        # / Anonymized — reused by the simulator, the averages AND the breakage (JS).
        'wallets_dormants': wallets_dormants,
        'depense_totale': depense_totale_centimes,
        'nb_vides': nb_vides,
        'total_charge': total_charge_centimes,
    }


def _calcul_temporel(asset):
    """
    Agrège les flux de CIRCULATION par mois et par type d'action (montants en euros).
    / Aggregates CIRCULATION flows by month and action type (amounts in euros).

    On exclut FIRST (genèse) et CREATION (frappe monétaire, déjà comptée dans le cycle de
    vie) pour ne pas gonfler le volume : une recharge = CREATION + REFILL.
    Une seule requête agrégée (TruncMonth + Sum + Count), donc pas de N+1.
    / Excludes FIRST (genesis) and CREATION (minting, already in the lifecycle) to avoid
      inflating volume: a top-up = CREATION + REFILL. Single aggregated query, no N+1.
    """
    actions_exclues = [Transaction.FIRST, Transaction.CREATION]

    lignes = (asset.transactions
              .exclude(action__in=actions_exclues)
              .annotate(mois=TruncMonth('datetime'))
              .values('mois', 'action')
              .annotate(nombre=Count('uuid'), total=Sum('amount'))
              .order_by('mois'))

    labels_action = dict(Transaction.TYPE_ACTION)

    # Liste continue des mois (du premier au dernier), sans trou : axe temporel honnête.
    # / Continuous list of months (first to last), no gap: honest time axis.
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


def _charge_courbe_survie(asset):
    """
    Lit la courbe de survie pre-calculee depuis database/courbe_survie.json.
    / Reads the pre-computed survival curve from database/courbe_survie.json.

    Ce fichier est produit a la main par la commande de gestion `courbe_survie`.
    On lit UNIQUEMENT un fichier (aucune requete base). Si le fichier n'existe pas
    ou ne contient pas cet asset (ex : monnaie locale), on renvoie {} : le front
    affichera alors seulement la courbe « avec fonte », sans la projection naturelle.
    / Reads ONLY a file (no DB query). Returns {} if missing for this asset.

    LOCALISATION : fedow_dashboard/views.py
    """
    chemin = Path(settings.BASE_DIR) / "database" / "courbe_survie.json"
    try:
        with open(chemin, encoding="utf-8") as fichier:
            donnees = json.load(fichier)
    except (OSError, ValueError):
        return {}

    asset_data = (donnees.get("assets") or {}).get(str(asset.uuid))
    if not asset_data:
        return {}

    # On ne renvoie que ce dont le front a besoin pour la projection naturelle.
    # / Only return what the front needs for the natural projection.
    return {
        "survie": asset_data.get("survie", []),
        "stock_par_age": asset_data.get("stock_par_age", []),
        "refill_par_age": asset_data.get("refill_par_age", []),
        "total_refill_centimes": asset_data.get("total_refill_centimes", 0),
        "horizon_mois": asset_data.get("horizon_mois", 24),
        "genere_le": donnees.get("genere_le"),
    }


def get_dashboard_asset(asset):
    """
    Calcule (et met en cache 5 min) les analyses du tableau de bord d'un asset.
    / Computes (and caches 5 min) the dashboard analyses for an asset.

    Le cache soulage la base de production (fragile). Il se vide automatiquement
    quand une fédération change (Federation.save() appelle cache.clear()).
    / Cache relieves the fragile production DB. It clears automatically when a
      federation changes (Federation.save() calls cache.clear()).
    """
    cle_cache = f"fedow_dashboard_asset_{asset.uuid}"
    donnees = cache.get(cle_cache)
    if donnees is not None:
        return donnees

    donnees = {
        'cycle_de_vie': _calcul_cycle_de_vie(asset),
        'monnaie_fondante_json': _calcul_monnaie_fondante(asset),
        'temporel_json': _calcul_temporel(asset),
        # Courbe de survie pre-calculee (fichier JSON), pour la projection naturelle.
        # / Pre-computed survival curve (JSON file), for the natural projection.
        'courbe_survie_json': _charge_courbe_survie(asset),
    }
    cache.set(cle_cache, donnees, 60 * 5)
    return donnees


def badgeuse_view(request, pk):
    asset = get_object_or_404(Asset, pk=pk)

    # Tout les actions de badgeuse sont des articles vendus avec la methode BADGEUSE
    ligne_badgeuse = asset.transactions.filter(
        action=Transaction.BADGE).order_by('card', 'datetime')

    dict_carte_passage = {}
    for ligne in ligne_badgeuse:
        ligne: Transaction
        if ligne.card not in dict_carte_passage:
            dict_carte_passage[ligne.card] = []
        dict_carte_passage[ligne.card].append(ligne)

    passages = []
    for carte, transactions in dict_carte_passage.items():
        horaires = [transaction.datetime for transaction in transactions]
        horaires_sorted = sorted(horaires)
        if len(horaires_sorted) % 2 != 0:
            horaires_sorted.append(None)

        couples_de_passage = list(zip(horaires_sorted[::2], horaires_sorted[1::2]))
        for horaires in couples_de_passage :
            # On veut la transaction qui correspond au premier horaire du couple de passage
            index = couples_de_passage.index(horaires) * 2 # il y a deux fois plus de transaction que de couple horaire
            passages.append({carte: {
                'horaires': horaires,
                'transaction': transactions[index],
            }
            })

    context = {
        'passages': passages,
    }

    return render(request, 'asset/badgeuse.html', context=context)


@staff_member_required
def asset_view(request, pk):
    # Réservé aux admins connectés (session admin). La home reste publique.
    # / Restricted to logged-in admins (admin session). The home stays public.
    asset = get_object_or_404(Asset, pk=pk)
    if asset.category == Asset.BADGE:
        return badgeuse_view(request, pk)

    # On précharge les relations affichées dans le tableau pour éviter les requêtes N+1.
    # / Preload relations shown in the table to avoid N+1 queries.
    transactions = (asset.transactions
                    .select_related('sender', 'sender__place',
                                    'receiver', 'receiver__place',
                                    'card', 'card__origin', 'card__origin__place')
                    .order_by('-datetime')[:50])

    context = {
        'asset': asset,
        # seulement les 50 dernières transactions :
        'transactions': transactions,
    }
    if asset.category == Asset.SUBSCRIPTION:
        return render(request, 'asset/asset_transactions_membership.html', context=context)

    # Tableau de bord enrichi : on ajoute les 3 analyses (calculs en cache).
    # / Enriched dashboard: add the 3 analyses (cached computations).
    context.update(get_dashboard_asset(asset))
    return render(request, 'asset/asset_transactions.html', context=context)


# Create your views here.
@staff_member_required
def place_view(request, pk):
    place = get_object_or_404(Place, pk=pk)
    accepted_assets = place.accepted_assets()
    place_federated_with = place.federated_with()

    context = {
        'assets': accepted_assets,
        'federations': place.federations.all(),
        'places': place_federated_with,
        'wallets': Wallet.objects.all(),
        'cards': Card.objects.all(),
    }
    return render(request, 'place/place.html', context=context)


# ---------------------------------------------------------------------------
# VUE RÉSEAU GLOBALE — calculs en LECTURE SEULE, mis en cache, zéro N+1
# / GLOBAL NETWORK VIEW — READ-ONLY computations, cached, no N+1
#
# Principe anti-mélange d'unités : on ne somme jamais des monnaies différentes.
# Les sommes monétaires sont par asset (masse) ou sur la seule FED (dormance).
# Les classements/pouls sont en nombre de transactions (agnostique à l'unité).
# / No unit mixing: monetary sums are per-asset (supply) or FED-only (dormancy);
#   rankings/pulse use transaction counts (unit-agnostic).
# ---------------------------------------------------------------------------

def _unite_categorie(category, currency_code):
    """Libellé d'unité pour une catégorie d'asset. / Unit label for an asset category."""
    if category == Asset.FIDELITY:
        return "pts"
    return (currency_code or "").upper()


# Couleur d'accent par catégorie de monnaie (lisible sur thème clair et sombre).
# / Accent color per currency category (readable on light and dark themes).
COULEUR_CATEGORIE = {
    Asset.TOKEN_LOCAL_FIAT: "#5e72e4",       # bleu : fiduciaire locale
    Asset.TOKEN_LOCAL_NOT_FIAT: "#fb6340",   # orange : cadeau
    Asset.STRIPE_FED_FIAT: "#2dce89",        # vert : fiduciaire fédérée
    Asset.TIME: "#825ee4",                   # violet : monnaie temps
    Asset.FIDELITY: "#f5a623",               # ambre : fidélité
    Asset.BADGE: "#11cdef",                  # cyan : badgeuse
}


def _masse_par_monnaie():
    """
    Masse monétaire par monnaie, groupée par catégorie (LECTURE SEULE, zéro N+1).
    / Money supply per currency, grouped by category (READ-ONLY, no N+1).

    4 agrégats groupés par asset + 1 lecture des assets. On ne somme jamais des
    monnaies différentes : chaque ligne porte sa propre unité.
    / 4 aggregates grouped by asset + 1 asset read. Never sum different currencies:
      each row carries its own unit.
    """
    circulation = {r['asset']: r['total'] for r in Token.objects
                   .filter(asset__archive=False, wallet__place__isnull=True)
                   .values('asset').annotate(total=Sum('value'))}
    lieux = {r['asset']: r['total'] for r in Token.objects
             .filter(asset__archive=False, wallet__place__isnull=False)
             .values('asset').annotate(total=Sum('value'))}
    banque = {r['asset']: r['total'] for r in Transaction.objects
              .filter(asset__archive=False, action=Transaction.DEPOSIT)
              .values('asset').annotate(total=Sum('amount'))}
    cree = {r['asset']: r['total'] for r in Transaction.objects
            .filter(asset__archive=False, action=Transaction.CREATION)
            .values('asset').annotate(total=Sum('amount'))}

    # On exclut les adhésions (SUB) et les badgeuses (BDG) : ce ne sont pas de la
    # « monnaie » au sens masse monétaire (les badgeuses ne sont pas utilisées — YAGNI).
    # / Exclude memberships (SUB) and badge assets (BDG): not "money" in the supply sense.
    par_categorie = {}  # code catégorie -> liste de lignes asset
    for asset in (Asset.objects.filter(archive=False)
                  .exclude(category__in=[Asset.SUBSCRIPTION, Asset.BADGE])
                  .order_by('category', 'name')):
        par_categorie.setdefault(asset.category, []).append({
            'uuid': str(asset.uuid),
            'name': asset.name,
            'unite': _unite_categorie(asset.category, asset.currency_code),
            'cree': round((cree.get(asset.uuid, 0) or 0) / 100, 2),
            'circulation': round((circulation.get(asset.uuid, 0) or 0) / 100, 2),
            'lieux': round((lieux.get(asset.uuid, 0) or 0) / 100, 2),
            'banque': round((banque.get(asset.uuid, 0) or 0) / 100, 2),
        })

    # Ordre d'affichage : la fiduciaire fédérée (primaire) en premier, puis les locales.
    # / Display order: federated (primary) fiat first, then local currencies.
    ordre_affichage = [
        Asset.STRIPE_FED_FIAT,
        Asset.TOKEN_LOCAL_FIAT,
        Asset.TOKEN_LOCAL_NOT_FIAT,
        Asset.TIME,
        Asset.FIDELITY,
    ]
    libelles = dict(Asset.CATEGORIES)
    resultat = []
    for code in ordre_affichage:
        if code in par_categorie:
            resultat.append({
                'categorie': str(libelles.get(code, code)),
                'code': code,
                'couleur': COULEUR_CATEGORIE.get(code, "#8898aa"),
                'assets': par_categorie[code],
            })
    return resultat


def _top_lieux(limite=10):
    """
    Top lieux par nombre de transactions (LECTURE SEULE, zéro N+1).
    / Top places by transaction count (READ-ONLY, no N+1).

    Tri par nombre de transactions (agnostique à l'unité). Le solde détenu est
    indicatif (toutes monnaies confondues).
    / Ranked by transaction count (unit-agnostic). Held balance is indicative (all currencies).
    """
    lieux = {}
    for r in (Transaction.objects.exclude(action=Transaction.FIRST)
              .filter(receiver__place__isnull=False)
              .values('receiver__place__uuid', 'receiver__place__name')
              .annotate(nb=Count('uuid'))):
        uuid_lieu = r['receiver__place__uuid']
        lieux[uuid_lieu] = {
            'uuid': str(uuid_lieu),
            'name': r['receiver__place__name'],
            'nb_tx': r['nb'],
            'solde_indicatif': 0.0,
        }

    for r in (Token.objects.filter(wallet__place__isnull=False)
              .values('wallet__place__uuid', 'wallet__place__name')
              .annotate(total=Sum('value'))):
        uuid_lieu = r['wallet__place__uuid']
        ligne = lieux.setdefault(uuid_lieu, {
            'uuid': str(uuid_lieu), 'name': r['wallet__place__name'],
            'nb_tx': 0, 'solde_indicatif': 0.0,
        })
        ligne['solde_indicatif'] = round((r['total'] or 0) / 100, 2)

    classement = sorted(lieux.values(), key=lambda ligne: ligne['nb_tx'], reverse=True)
    return classement[:limite]


def _pouls_reseau():
    """
    Pouls du réseau : nombre de transactions par mois (LECTURE SEULE).
    / Network pulse: transaction count per month (READ-ONLY).

    On compte les transactions (pas les montants) car les monnaies ont des unités
    différentes : additionner des euros et des heures n'aurait pas de sens.
    / We count transactions (not amounts) because currencies have different units.
    """
    lignes = (Transaction.objects.exclude(action=Transaction.FIRST)
              .annotate(mois=TruncMonth('datetime'))
              .values('mois').annotate(nb=Count('uuid')).order_by('mois'))
    labels, data = [], []
    for ligne in lignes:
        if not ligne['mois']:
            continue
        labels.append(ligne['mois'].strftime('%Y-%m'))
        data.append(ligne['nb'])
    return {'labels': labels, 'data': data, 'vide': len(labels) == 0}


def _dormance_fed():
    """
    Dormance de la monnaie fédérée uniquement (LECTURE SEULE).
    / Dormancy of the federated currency only (READ-ONLY).

    La dormance n'a de sens au niveau réseau que pour la monnaie fédérée (inter-lieux).
    Chaque lieu gère sa propre monnaie locale.
    / Dormancy only makes sense network-wide for the federated currency. Each place
      manages its own local currency.
    """
    fed = Asset.objects.filter(category=Asset.STRIPE_FED_FIAT).first()
    if fed is None:
        return None
    fondante = _calcul_monnaie_fondante(fed)
    # On n'a pas besoin de la liste anonymisée ici (allège le cache).
    # / We don't need the anonymized list here (lighten the cache).
    fondante.pop('wallets_dormants', None)
    fondante['asset_uuid'] = str(fed.uuid)
    fondante['asset_name'] = fed.name
    return fondante


def get_dashboard_reseau():
    """
    Agrège (et met en cache 5 min) la vue réseau globale. LECTURE SEULE, zéro N+1.
    / Aggregates (and caches 5 min) the global network view. READ-ONLY, no N+1.

    Ne contient que des données sérialisables (pas d'objets ORM) pour un cache propre.
    / Contains only serializable data (no ORM objects) for a clean cache.
    """
    cle_cache = "fedow_dashboard_reseau"
    donnees = cache.get(cle_cache)
    if donnees is not None:
        return donnees

    donnees = {
        'masse': _masse_par_monnaie(),
        'top_lieux': _top_lieux(),
        'pouls': _pouls_reseau(),
        'dormance_fed': _dormance_fed(),
    }
    cache.set(cle_cache, donnees, 60 * 5)
    return donnees


# @cache_page(60 * 15)
def index(request):
    """
    Vue d'ensemble réseau (admin) : masse par monnaie, top lieux, activité, dormance FED.
    / Network overview (admin): supply per currency, top places, activity, FED dormancy.
    """
    # Données agrégées en cache (sérialisables).
    # / Cached aggregated data (serializable).
    contexte = dict(get_dashboard_reseau())

    # Dernières transactions du réseau (préchargées, non mises en cache car objets ORM).
    # / Latest network transactions (prefetched, not cached because ORM objects).
    contexte['dernieres_transactions'] = (Transaction.objects
                                          .exclude(action=Transaction.FIRST)
                                          .select_related('asset', 'sender', 'sender__place',
                                                          'receiver', 'receiver__place')
                                          .order_by('-datetime')[:15])

    # Compteurs simples.
    # / Simple counters.
    # Compteur « Monnaies » aligné sur la masse : on exclut adhésions (SUB) et badgeuses (BDG).
    # / "Currencies" counter aligned with the supply table: exclude memberships and badge assets.
    contexte['nb_assets'] = (Asset.objects.filter(archive=False)
                             .exclude(category__in=[Asset.SUBSCRIPTION, Asset.BADGE])
                             .count())
    contexte['nb_places'] = Place.objects.count()
    contexte['nb_federations'] = Federation.objects.count()
    contexte['nb_wallets'] = Wallet.objects.count()
    contexte['nb_cards'] = Card.objects.count()

    logger.info("Index (vue réseau) rendered")
    return render(request, 'index/index.html', context=contexte)
