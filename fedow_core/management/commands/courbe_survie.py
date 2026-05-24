import json
from collections import defaultdict, deque
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from fedow_core.models import Asset, Transaction, Wallet


def _mois_ecoules(debut, fin):
    """
    Nombre de mois calendaires entre deux dates. Jamais negatif.
    / Calendar months between two dates. Never negative.
    """
    nb = (fin.year - debut.year) * 12 + (fin.month - debut.month)
    if nb < 0:
        return 0
    return nb


class Command(BaseCommand):
    """
    Calcule la courbe de survie de la monnaie federee (FED).
    / Computes the survival curve of the federated currency (FED).

    LOCALISATION : fedow_core/management/commands/courbe_survie.py

    But : repondre a "sur 100 FED charges sur une carte, combien reste-t-il
    encore sur la carte apres N mois ?". C'est le moteur commun qui alimentera
    le simulateur de fonte ET la projection du dashboard.

    Methode (en clair) :
    1. On parcourt toutes les transactions FED dans l'ordre du temps.
    2. Pour chaque carte (wallet user), on tient une file FIFO de tranches
       d'argent charge. Une depense consomme l'argent le plus ancien d'abord.
    3. Chaque tranche recoit ainsi une duree de vie : "depensee a X mois" ou
       "encore vivante a Y mois".
    4. On en deduit, mois par mois, le taux de depense parmi l'argent encore
       "au risque" (Kaplan-Meier discret). Cela neutralise le biais de
       saisonnalite : l'argent recent n'est compte qu'aux ages qu'il a eu le
       temps d'atteindre.

    LECTURE SEULE : aucune ecriture en base, aucune migration. On lit la chaine
    et on ecrit un fichier JSON.
    / READ-ONLY: no DB write, no migration. Reads the chain, writes a JSON file.
    """

    help = (
        "Calcule la courbe de survie de la monnaie federee (FED) a partir de la "
        "chaine et ecrit le resultat dans un fichier JSON. LECTURE SEULE."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--horizon",
            type=int,
            default=24,
            help="Horizon de la courbe, en mois (defaut: 24).",
        )
        parser.add_argument(
            "--sortie",
            type=str,
            default=None,
            help="Chemin du fichier JSON (defaut: BASE_DIR/database/courbe_survie.json).",
        )

    def handle(self, *args, **options):
        horizon = options["horizon"]
        if horizon < 1:
            raise CommandError("--horizon doit etre un entier >= 1.")

        # ---------------------------------------------------------------
        # 1. Asset FED (monnaie federee). Il est unique en base.
        # / FED asset (federated currency). Unique in DB.
        # ---------------------------------------------------------------
        try:
            fed = Asset.objects.get(category=Asset.STRIPE_FED_FIAT)
        except Asset.DoesNotExist:
            raise CommandError("Aucun asset FED (STRIPE_FED_FIAT) trouve en base.")

        # ---------------------------------------------------------------
        # 2. Ensemble des wallets "user" : ni lieu, ni wallet primaire.
        #    Meme definition que le reste du dashboard.
        # / Set of "user" wallets: not a place, not the primary wallet.
        # ---------------------------------------------------------------
        user_wallets = set(
            Wallet.objects.filter(place__isnull=True, primary__isnull=True)
            .values_list("uuid", flat=True)
        )

        # ---------------------------------------------------------------
        # 3. Parcours chronologique de toutes les transactions FED.
        #    files[wallet] = file FIFO de tranches [montant_restant, date_credit].
        # / Time-ordered walk of all FED transactions, FIFO queue per wallet.
        # ---------------------------------------------------------------
        files = defaultdict(deque)

        # fin_event[age] = montant depense (evenement) a cet age, en mois.
        # fin_cens[age]  = montant encore vivant (censure) a cet age, en mois.
        # / spent amount per age (event) and still-alive amount per age (censored)
        fin_event = defaultdict(int)
        fin_cens = defaultdict(int)

        total_refill = 0      # somme des vraies recharges (action REFILL), en centimes
        nb_transactions = 0

        transactions = (
            Transaction.objects
            .filter(asset=fed)
            .order_by("datetime")
            .values("sender_id", "receiver_id", "amount", "datetime", "action")
            .iterator(chunk_size=2000)
        )

        for tx in transactions:
            nb_transactions += 1
            montant = tx["amount"]
            sender = tx["sender_id"]
            receiver = tx["receiver_id"]
            dt = tx["datetime"]
            action = tx["action"]

            # CREDIT : de l'argent arrive sur une carte user -> nouvelle tranche.
            # / Credit: money enters a user card -> new tranche.
            if receiver in user_wallets:
                files[receiver].append([montant, dt])
                if action == Transaction.REFILL:
                    total_refill += montant

            # DEBIT : de l'argent sort d'une carte user -> on consomme en FIFO.
            # / Debit: money leaves a user card -> consume FIFO.
            if sender in user_wallets:
                a_consommer = montant
                file = files[sender]
                while a_consommer > 0 and file:
                    tranche = file[0]
                    pris = tranche[0] if tranche[0] <= a_consommer else a_consommer
                    age = _mois_ecoules(tranche[1], dt)
                    # Depense (evenement) a cet age. Au-dela de l'horizon,
                    # l'argent a "survecu" jusqu'au bord de la fenetre.
                    # / Spend (event); beyond horizon = survived to the edge.
                    if age >= horizon:
                        fin_cens[horizon] += pris
                    else:
                        fin_event[age] += pris
                    tranche[0] -= pris
                    a_consommer -= pris
                    if tranche[0] == 0:
                        file.popleft()
                # Surplus a_consommer > 0 : argent charge avant le debut des
                # donnees, non tracable. On l'ignore.
                # / Leftover = money loaded before our data starts -> ignored.

        # ---------------------------------------------------------------
        # 4. Ce qui reste dans les files = argent encore vivant (censure).
        # / What remains in the queues = still-alive money (censored).
        # ---------------------------------------------------------------
        maintenant = timezone.now()
        nb_wallets_vivants = 0
        # stock_par_age[age] = montant actuellement sur les cartes a cet age (en centimes).
        # Sert a projeter le stock actuel avec la courbe de survie (dashboard).
        # / Current on-card amount per age; used to project the current stock.
        stock_par_age = defaultdict(int)
        # nb_par_age[age] = nombre de tranches vivantes a cet age (proxy du nombre
        # de cartes). Sert a etaler le mode de fonte "montant fixe par mois".
        # / live-tranche count per age (proxy for number of cards), for the fixed mode.
        nb_par_age = defaultdict(int)
        for file in files.values():
            wallet_a_du_vivant = False
            for tranche in file:
                montant_restant = tranche[0]
                date_credit = tranche[1]
                if montant_restant > 0:
                    wallet_a_du_vivant = True
                    age = _mois_ecoules(date_credit, maintenant)
                    age_c = age if age < horizon else horizon
                    fin_cens[age_c] += montant_restant
                    stock_par_age[age_c] += montant_restant
                    nb_par_age[age_c] += 1
            if wallet_a_du_vivant:
                nb_wallets_vivants += 1

        # ---------------------------------------------------------------
        # 5. Courbe de survie (Kaplan-Meier discret, par mois d'age).
        #    A chaque mois : taux de depense parmi l'argent encore au risque,
        #    puis survie = produit des (1 - taux).
        # / Discrete Kaplan-Meier survival curve per age-month.
        # ---------------------------------------------------------------
        total_suivi = sum(fin_event.values()) + sum(fin_cens.values())

        courbe = [{"age_mois": 0, "part_restante": 1.0}]
        survie = 1.0
        deja_fini = 0   # argent sorti du risque (depense ou censure) aux ages < a
        for a in range(0, horizon):
            au_risque = total_suivi - deja_fini
            evenements_a = fin_event.get(a, 0)
            if au_risque > 0:
                hasard = evenements_a / au_risque
            else:
                hasard = 0.0
            survie = survie * (1.0 - hasard)
            deja_fini += evenements_a + fin_cens.get(a, 0)
            courbe.append({"age_mois": a + 1, "part_restante": round(survie, 4)})

        # Distribution du stock actuel par age (pour la projection cote dashboard).
        # / Current stock distribution per age (for the dashboard projection).
        stock_liste = [
            {
                "age_mois": age,
                "montant_centimes": montant,
                "nb_cartes": nb_par_age.get(age, 0),
            }
            for age, montant in sorted(stock_par_age.items())
        ]

        # ---------------------------------------------------------------
        # 6. Ecriture du resultat dans le JSON. AUCUNE ecriture en base.
        # / Write the result to JSON. NO database write.
        # ---------------------------------------------------------------
        if options["sortie"]:
            chemin = Path(options["sortie"])
        else:
            chemin = Path(settings.BASE_DIR) / "database" / "courbe_survie.json"

        donnees = {
            "genere_le": maintenant.isoformat(),
            "methode": "FIFO par wallet user + survie Kaplan-Meier discrete (par mois d'age)",
            "lecture_seule": True,
            "assets": {
                str(fed.uuid): {
                    "asset_name": fed.name,
                    "category": fed.category,
                    "horizon_mois": horizon,
                    "nb_transactions": nb_transactions,
                    "nb_wallets_avec_solde": nb_wallets_vivants,
                    "total_refill_centimes": total_refill,
                    "total_suivi_centimes": total_suivi,
                    "survie": courbe,
                    "stock_par_age": stock_liste,
                }
            },
        }

        with open(chemin, "w", encoding="utf-8") as fichier:
            json.dump(donnees, fichier, ensure_ascii=False, indent=2)

        # ---------------------------------------------------------------
        # Resume console
        # ---------------------------------------------------------------
        self.stdout.write(self.style.SUCCESS(f"Courbe de survie ecrite : {chemin}"))
        self.stdout.write(self.style.NOTICE(
            f"FED={fed.name} | tx={nb_transactions} "
            f"| refill={total_refill / 100:.2f} | suivi={total_suivi / 100:.2f} "
            f"| cartes avec solde={nb_wallets_vivants} | horizon={horizon} mois"
        ))
        reperes = {p["age_mois"]: p["part_restante"] for p in courbe}
        for mois in (1, 3, 6, 12, horizon):
            if mois in reperes:
                self.stdout.write(f"  survie a {mois:>2} mois : {reperes[mois] * 100:5.1f} %")
