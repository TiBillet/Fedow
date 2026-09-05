"""
Rattrapage des recharges Stripe payees mais jamais creditees.
/ Repair Stripe refills that were paid but never credited.

LOCALISATION : fedow_core/management/commands/rattrapage_recharges_perdues.py

But : terminer les recharges restees a mi-chemin. La monnaie a bien ete creee
(transaction CREATION committee, wallet primaire credite), mais le REFILL qui
devait la transferer au porteur a echoue. Il ne s'agit donc PAS de creer de la
monnaie : elle existe deja, on la deplace enfin.

Methode (en clair) :
 1. On recense les CREATION Stripe qui n'ont aucun REFILL sur le meme checkout.
 2. On resout le wallet destinataire (carte, metadata signee, ou user du checkout).
 3. Selon le lot demande, on ecrit les transactions manquantes :
      lot A : REFILL primaire -> porteur, puis checkout repasse en PAID.
              Le porteur choisira ensuite de se faire rembourser ou non.
      lot B : REFILL puis REFUND vers le wallet primaire, pour les paiements
              DEJA rembourses a la main sur Stripe. Aucun appel Stripe ici.
      lot C : REFILL puis REFUND vers le wallet d'un lieu, quand le lieu a
              avance la valeur au porteur (credit en monnaie locale sans
              encaissement). Le lieu recupere son du au prochain virement.
 4. On vide le cache : les totaux admin et les soldes Lespass sont caches 5 min.

Pourquoi REFILL+REFUND et pas CORRECTION pour les lots B et C : l'action
CORRECTION est volontairement absente des listes de reconcile_tokens.py
(ACTIONS_CREDIT_RECEIVER / ACTIONS_DEBIT_SENDER). Un transfert de valeur ecrit
en CORRECTION creerait un ecart que le prochain "reconcile_tokens --apply"
annulerait silencieusement. REFILL et REFUND, eux, sont comptes des deux cotes.

DRY-RUN PAR DEFAUT : aucune ecriture sans --apply.
/ DRY-RUN by default: no write without --apply.

Contexte : incident des 28-29/08/2026, 24 recharges / 381,00 EUR.
Cf TECH_DEV/DRIFT/README.md et le correctif de Transaction.save().
"""
import logging

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction

from fedow_core.models import (
    Asset, CheckoutStripe, Configuration, Place, Token, Transaction,
)

logger = logging.getLogger(__name__)

LOTS = ("A", "B", "C")


class Command(BaseCommand):
    help = (
        "Termine les recharges Stripe payees mais jamais creditees (CREATION sans "
        "REFILL). Dry-run par defaut ; --apply pour ecrire."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Ecrit les transactions. Sans ce flag : dry-run (aucune ecriture).",
        )
        parser.add_argument(
            "--lot", choices=LOTS, default="A",
            help="A: rendre au porteur (defaut). B: deja rembourse sur Stripe. "
                 "C: reverser a un lieu qui a avance la valeur.",
        )
        parser.add_argument(
            "--checkout", nargs="*", default=[],
            help="Limite aux checkouts donnes (uuid ou checkout_session_id_stripe). "
                 "Obligatoire pour les lots B et C.",
        )
        parser.add_argument(
            "--place", default=None,
            help="Lot C uniquement : nom ou uuid du lieu destinataire du REFUND.",
        )
        parser.add_argument(
            "--total-attendu", type=int, default=None,
            help="Garde-fou : total en centimes des cas retenus. Refuse si different.",
        )
        parser.add_argument(
            "--max-cas", type=int, default=50,
            help="Garde-fou : refuse au-dela de N cas (defaut 50).",
        )
        parser.add_argument(
            "--exclure", nargs="*", default=[],
            help="Checkouts a ignorer (uuid ou checkout_session_id_stripe).",
        )
        parser.add_argument(
            "--commentaire", default="Rattrapage recharge perdue (cf TECH_DEV/DRIFT)",
            help="Commentaire porte par les transactions creees.",
        )

    # ------------------------------------------------------------------
    # 1. Selection des cas
    # ------------------------------------------------------------------

    def _creations_orphelines(self, checkouts_demandes, checkouts_exclus):
        # Une CREATION Stripe sans REFILL sur le meme checkout = recherche exacte
        # et auto-idempotente : des qu'un REFILL est ecrit, le cas sort du peri-
        # metre. Relancer la commande ne refait donc rien.
        # / A mint with no refill on the same checkout: exact and self-idempotent.
        checkouts_deja_recharges = Transaction.objects.filter(
            action=Transaction.REFILL, checkout_stripe__isnull=False,
        ).values_list("checkout_stripe_id", flat=True)

        creations = Transaction.objects.filter(
            action=Transaction.CREATION,
            asset__category=Asset.STRIPE_FED_FIAT,
            checkout_stripe__isnull=False,
        ).exclude(
            checkout_stripe_id__in=checkouts_deja_recharges
        ).select_related("checkout_stripe", "card", "asset").order_by("datetime")

        if checkouts_demandes:
            creations = [c for c in creations if self._correspond(c, checkouts_demandes)]
        else:
            creations = list(creations)
        if checkouts_exclus:
            creations = [c for c in creations if not self._correspond(c, checkouts_exclus)]

        # Un checkout deja en REFUND a ete rembourse (par la vue de remboursement ou
        # a la main sur Stripe) : l'argent n'est plus chez Stripe. Le crediter serait
        # une seconde sortie d'argent. On l'ecarte, et on le DIT.
        # / A checkout already in REFUND was paid back: crediting it would pay twice.
        deja_rembourses = [c for c in creations
                           if c.checkout_stripe.status == CheckoutStripe.REFUND]
        creations = [c for c in creations
                     if c.checkout_stripe.status != CheckoutStripe.REFUND]
        return creations, deja_rembourses

    @staticmethod
    def _correspond(creation, identifiants):
        checkout = creation.checkout_stripe
        connus = {str(checkout.uuid), str(checkout.uuid).replace("-", "")}
        if checkout.checkout_session_id_stripe:
            connus.add(checkout.checkout_session_id_stripe)
        return any(str(i) in connus for i in identifiants)

    # ------------------------------------------------------------------
    # 2. Resolution du destinataire
    # ------------------------------------------------------------------

    def _wallet_du_porteur(self, creation):
        """
        Retourne (wallet, origine_de_la_resolution) ou (None, raison).
        On n'appelle JAMAIS Card.get_wallet() : cette methode CREE et sauvegarde
        un wallet ephemere quand la carte n'en a pas (models.py), effet de bord
        inacceptable pendant un dry-run.
        / Never call Card.get_wallet(): it creates a wallet as a side effect.
        """
        carte = creation.card
        checkout = creation.checkout_stripe

        # ORDRE DE PREFERENCE : un compte identifie passe TOUJOURS avant un wallet
        # ephemere anonyme. Un wallet ephemere n'est joignable qu'avec la carte
        # physique en main : crediter celui d'un porteur qui a un compte rendrait
        # son argent inaccessible des qu'il a quitte l'evenement.
        # / An identified account always wins over an anonymous ephemeral wallet,
        # which is only reachable with the physical card in hand.
        if carte is not None and carte.user_id:
            return carte.user.wallet, f"carte {carte.number_printed} (compte)"

        # Flux web : la metadata est signee par Django et porte le token du user.
        # Flux TPE : metadata brute de Stripe, la signature ne passera pas.
        # / Web flow: Django-signed metadata. Terminal flow: raw Stripe metadata.
        try:
            donnees_signees = checkout.unsign_metadata()
            token_utilisateur = Token.objects.get(uuid=donnees_signees.get("user_token"))
            return token_utilisateur.wallet, "metadata signee"
        except Exception:
            pass

        if checkout.user_id:
            return checkout.user.wallet, "compte du checkout"

        # Dernier recours : la carte anonyme. Le porteur devra la presenter.
        # / Last resort: the anonymous card. The holder must present it.
        if carte is not None and carte.wallet_ephemere_id:
            return carte.wallet_ephemere, f"carte {carte.number_printed} (anonyme)"
        return None, "NON RESOLU"

    @staticmethod
    def _suivre_les_fusions(wallet):
        # Un wallet ephemere fusionne dans un compte n'est plus le bon destinataire :
        # la valeur vit desormais sur le wallet cible.
        # / Follow FUSION hops so we credit the surviving wallet.
        vus = set()
        while True:
            fusion = Transaction.objects.filter(
                action=Transaction.FUSION, sender=wallet).order_by("datetime").last()
            if fusion is None or fusion.receiver_id in vus:
                return wallet
            vus.add(wallet.pk)
            wallet = fusion.receiver

    # ------------------------------------------------------------------
    # 3. Ecriture
    # ------------------------------------------------------------------

    def _ecrire_un_cas(self, creation, wallet_porteur, lot, wallet_du_lieu, commentaire):
        wallet_primaire = Configuration.get_solo().primary_wallet
        checkout = creation.checkout_stripe

        # Tout-ou-rien par cas : REFILL + REFUND + statut. On ne prend surtout pas
        # un seul atomic pour toute la commande, gunicorn sert pendant ce temps et
        # le verrou d'ecriture SQLite est global.
        # / All-or-nothing per case; never one transaction for the whole run.
        with db_transaction.atomic():
            # Re-check dans la fenetre entre la selection et l'ecriture.
            # / Re-check the window between selection and write.
            if Transaction.objects.filter(
                    action=Transaction.REFILL, checkout_stripe=checkout).exists():
                return None, "deja recharge entre-temps"

            refill = Transaction(
                ip="127.0.0.1",
                checkout_stripe=checkout,
                sender=wallet_primaire,
                receiver=wallet_porteur,
                asset=creation.asset,
                amount=creation.amount,
                action=Transaction.REFILL,
                comment=commentaire,
                # La carte n'est posee que si elle pointe bien le wallet credite :
                # Transaction.save() l'exige, et une fusion a pu decaler le wallet.
                # / Only attach the card when it still maps to the credited wallet.
                card=creation.card if (
                    creation.card is not None
                    and (creation.card.user_id and creation.card.user.wallet_id == wallet_porteur.pk
                         or creation.card.wallet_ephemere_id == wallet_porteur.pk)
                ) else None,
            )
            refill.creation_associee = creation
            refill.save(force_insert=True)

            if lot == "A":
                # Sans ce statut, refund_fed_by_signature ignore le checkout et
                # repond 402 au porteur alors que son solde est bien credite.
                # / Without PAID, the refund view ignores the checkout (402).
                checkout.status = CheckoutStripe.PAID
                checkout.save(update_fields=["status"])
                return refill, None

            destinataire = wallet_primaire if lot == "B" else wallet_du_lieu
            remboursement = Transaction.objects.create(
                ip="127.0.0.1",
                checkout_stripe=checkout,
                sender=wallet_porteur,
                receiver=destinataire,
                asset=creation.asset,
                amount=creation.amount,
                action=Transaction.REFUND,
                comment=commentaire,
            )
            # Aucun de ces deux lots ne doit rester une source de remboursement Stripe :
            # lot B, l'argent est deja rendu ; lot C, la valeur appartient au lieu.
            # refund_fed_by_signature ne retient que PAID et WALLET_USER_OK
            # (views.py) : WALLET_PRIMARY_OK sort donc le checkout du jeu.
            # / Neither lot may remain a refundable source: the refund view only
            # accepts PAID and WALLET_USER_OK.
            checkout.status = (CheckoutStripe.REFUND if lot == "B"
                               else CheckoutStripe.WALLET_PRIMARY_OK)
            checkout.save(update_fields=["status"])
            return remboursement, None

    @staticmethod
    def _identifiant_lisible(checkout):
        # Un checkout porte soit une session Stripe, soit une facture (renouvellement
        # d'adhesion), soit ni l'une ni l'autre : on retombe sur son uuid.
        # / Session id, invoice id, or the uuid as a last resort.
        return (checkout.checkout_session_id_stripe
                or checkout.invoice_stripe_id
                or str(checkout.uuid))

    def _signaler_les_checkouts_sans_transaction(self):
        """
        Une panne peut laisser un checkout qui AFFIRME un paiement alors qu'aucune
        transaction n'existe : argent encaisse chez Stripe, rien en base.
        / A crash can leave a checkout claiming payment with no transaction at all.

        Ce cas n'est PAS rattrapable par cette commande (elle part des CREATION
        orphelines, or ici il n'y a aucune CREATION). On se contente donc de le
        SIGNALER, ce qui suffit : il ne s'est jamais produit (0 sur 7 581 paiements
        au 05/09/2026), et le corriger demanderait de modifier les chemins
        d'encaissement eux-memes.

        Ce controle existe parce que rendre la paire CREATION+REFILL atomique a
        supprime la trace que laissaient ces pannes : avant, une CREATION orpheline
        restait et cette commande la voyait ; desormais le rollback n'en laisse
        aucune. On remplace donc la trace perdue par une detection explicite.
        / Kept as detection only: making the pair atomic removed the orphan CREATION
        that used to reveal such crashes.
        """
        # ERROR est dans la liste, et c'est essentiel : ce statut n'est pose qu'APRES
        # confirmation du paiement par Stripe (views.py, sous payment_status=='paid'),
        # il signifie donc "paye, mais credit refuse". C'etait la signature de
        # l'incident du 28/08 : 18 des 26 cas. Avant l'atomicite, ces cas laissaient
        # une CREATION reperable ; desormais le rollback n'en laisse aucune, et sans
        # ERROR ici le meme incident rejoue demain serait invisible.
        # On ne filtre PAS sur checkout_session_id_stripe : les renouvellements
        # d'adhesion Lespass n'en ont pas (ils portent un invoice_stripe_id), soit
        # 56 % des checkouts Lespass qui seraient sinon hors detection.
        # / ERROR is included on purpose: it is only set after Stripe confirms
        # payment, and it was the signature of 18 of the 26 incident cases.
        anomalies = CheckoutStripe.objects.filter(
            status__in=[CheckoutStripe.PAID, CheckoutStripe.WALLET_USER_OK,
                        CheckoutStripe.FROM_LESPASS, CheckoutStripe.REFUND,
                        CheckoutStripe.ERROR],
        ).exclude(
            uuid__in=Transaction.objects.filter(
                checkout_stripe__isnull=False).values_list("checkout_stripe_id", flat=True)
        )
        nombre = anomalies.count()
        if not nombre:
            self.stdout.write("Controle : 0 checkout paye sans transaction. OK.")
            return
        message = (f"ATTENTION : {nombre} checkout(s) affirment un paiement sans aucune "
                   f"transaction. Argent encaisse chez Stripe, rien en base. "
                   f"NON rattrapable par cette commande, verification manuelle requise.")
        # logger.error -> evenement Sentry (event_level=ERROR par defaut).
        # De l'argent encaisse sans contrepartie doit reveiller quelqu'un.
        # / logger.error raises a Sentry event: money in without counterpart.
        # Une seule evaluation : sinon le log Sentry et la sortie console pourraient
        # differer si une ecriture concurrente change la selection entre les deux.
        # / Evaluate once, so the Sentry log and the console listing cannot diverge.
        echantillon = list(anomalies[:20])
        logger.error(message + " " + ", ".join(
            self._identifiant_lisible(c) for c in echantillon))
        self.stdout.write(message + " :")
        for checkout in echantillon:
            self.stdout.write(
                f"   {checkout.datetime.strftime('%Y-%m-%d %H:%M')}  statut={checkout.status}  "
                f"{self._identifiant_lisible(checkout)}")

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        lot = options["lot"]
        checkouts_demandes = options["checkout"]
        commentaire = options["commentaire"]

        if lot in ("B", "C") and not checkouts_demandes:
            raise CommandError(f"Lot {lot} : --checkout est obligatoire (ciblage explicite).")

        # Le total attendu est le seul garde-fou qui oblige a relire le dry-run avant
        # d'ecrire de l'argent reel. On ne s'en passe pas.
        # / The expected total forces a human to read the dry-run before writing money.
        if options["apply"] and options["total_attendu"] is None:
            raise CommandError("--apply exige --total-attendu (en centimes). "
                               "Lancer d'abord le dry-run pour lire le total.")

        wallet_du_lieu = None
        if lot == "C":
            if not options["place"]:
                raise CommandError("Lot C : --place est obligatoire (destinataire du REFUND).")
            lieu = Place.objects.filter(name=options["place"]).first()
            if lieu is None:
                try:
                    lieu = Place.objects.filter(pk=str(options["place"]).replace("-", "")).first()
                except (ValidationError, ValueError):
                    lieu = None
            if lieu is None:
                raise CommandError(f"Lieu introuvable : {options['place']}")
            wallet_du_lieu = lieu.wallet
            self.stdout.write(f"Lot C : destinataire {lieu.name} ({wallet_du_lieu.uuid})")

        # Controle independant du rattrapage : il doit tourner meme quand il n'y a
        # aucune recharge orpheline. / Runs even when there is nothing to repair.
        self._signaler_les_checkouts_sans_transaction()

        creations, deja_rembourses = self._creations_orphelines(
            checkouts_demandes, options["exclure"])
        for creation in deja_rembourses:
            message = (f"IGNORE (checkout deja en REFUND, argent deja sorti) "
                       f"{creation.amount / 100:.2f} EUR  {creation.checkout_stripe.uuid}")
            logger.warning(f"rattrapage_recharges_perdues : {message}")
            self.stdout.write("  " + message)

        # Un --checkout demande mais introuvable est une coquille, pas un no-op.
        # / A requested checkout that matches nothing is a typo, not a no-op.
        if checkouts_demandes:
            trouves = {i for i in checkouts_demandes
                       if any(self._correspond(c, [i]) for c in creations + deja_rembourses)}
            manquants = [i for i in checkouts_demandes if i not in trouves]
            if manquants:
                raise CommandError(
                    "Checkouts demandes introuvables (ou deja recharges) : "
                    + ", ".join(manquants))

        if not creations:
            self.stdout.write("Aucune recharge orpheline. Rien a faire.")
            return

        configuration = Configuration.get_solo()
        wallet_primaire = configuration.primary_wallet

        cas_traitables, cas_bloques, total = [], [], 0
        for creation in creations:
            wallet_porteur, origine = self._wallet_du_porteur(creation)
            if wallet_porteur is None:
                cas_bloques.append((creation, origine))
                continue
            wallet_porteur = self._suivre_les_fusions(wallet_porteur)
            cas_traitables.append((creation, wallet_porteur, origine))
            total += creation.amount

        self.stdout.write(
            f"=== lot {lot} | {len(cas_traitables)} recharges | total {total / 100:.2f} EUR ===")
        for creation, wallet_porteur, origine in cas_traitables:
            checkout = creation.checkout_stripe
            self.stdout.write(
                f"  {creation.datetime.strftime('%Y-%m-%d %H:%M')}  "
                f"{creation.amount / 100:>8.2f} EUR  statut={checkout.status}  "
                f"wallet:{str(wallet_porteur.uuid)[:8]}  ({origine})  "
                f"{(checkout.checkout_session_id_stripe or '')[:24]}")
        for creation, raison in cas_bloques:
            message = (f"A VERIFIER  {creation.amount / 100:.2f} EUR  {raison}  "
                       f"checkout {creation.checkout_stripe.uuid}")
            # Destinataire non resolu : personne ne sera credite sans intervention.
            # / Unresolved recipient: nobody gets credited without a human.
            logger.error(f"rattrapage_recharges_perdues : {message}")
            self.stdout.write("  " + message)

        # ---- garde-fous / guards ----
        if cas_bloques:
            self.stdout.write(f"{len(cas_bloques)} cas non resolus, exclus de l'ecriture.")
        if len(cas_traitables) > options["max_cas"]:
            raise CommandError(
                f"{len(cas_traitables)} cas > --max-cas {options['max_cas']}. Refus.")
        if options["total_attendu"] is not None and total != options["total_attendu"]:
            raise CommandError(
                f"Total {total} != --total-attendu {options['total_attendu']}. Refus.")

        if cas_traitables:
            # Tous les cas portent le meme asset federe : un seul token a verifier.
            # / Every case is on the same federated asset: one token to check.
            asset_federe = cas_traitables[0][0].asset
            if any(cas[0].asset_id != asset_federe.pk for cas in cas_traitables):
                raise CommandError("Plusieurs assets federes dans la selection. Refus.")
            try:
                token_primaire = Token.objects.get(wallet=wallet_primaire, asset=asset_federe)
            except Token.DoesNotExist:
                raise CommandError("Le wallet primaire n'a pas de token sur cet asset.")
            self.stdout.write(f"Solde du wallet primaire : {token_primaire.value / 100:.2f} EUR")
            if token_primaire.value < total:
                raise CommandError(
                    f"Solde du wallet primaire insuffisant : "
                    f"{token_primaire.value / 100:.2f} EUR < {total / 100:.2f} EUR.")

        if not options["apply"]:
            self.stdout.write("DRY-RUN : aucune ecriture. Relancer avec --apply pour ecrire.")
            return

        # ---- ecriture, un cas a la fois (sequentiel => pas de nouveau fork) ----
        # / Sequential writes, one case at a time.
        ecrits, ignores, echecs = 0, 0, []
        for creation, wallet_porteur, _origine in cas_traitables:
            try:
                resultat, raison = self._ecrire_un_cas(
                    creation, wallet_porteur, lot, wallet_du_lieu, commentaire)
                if resultat is None:
                    ignores += 1
                    self.stdout.write(f"  ignore ({raison}) : {creation.checkout_stripe.uuid}")
                else:
                    ecrits += 1
            except Exception as erreur:
                echecs.append((creation, erreur))
                # Echec d'une ecriture d'argent : evenement Sentry.
                # / A money write failed: Sentry event.
                logger.error(
                    f"rattrapage_recharges_perdues ECHEC checkout "
                    f"{creation.checkout_stripe.uuid} : {erreur}", exc_info=True)
                self.stdout.write(f"  ECHEC {creation.checkout_stripe.uuid} : {erreur}")

        # Les totaux admin, total_by_place et les wallets serialises sont caches
        # 5 min : sans ce clear, Lespass et le dashboard afficheront des soldes
        # faux jusqu'a 5 minutes apres le rattrapage.
        # / Clear the 5-minute caches, else balances stay stale in Lespass.
        cache.clear()

        self.stdout.write(f"OK : {ecrits} recharges rattrapees, {ignores} ignorees, "
                          f"{len(echecs)} en echec.")
        if echecs:
            raise CommandError(f"{len(echecs)} cas en echec, voir ci-dessus.")
