from django.core.management.base import BaseCommand
from django.db.models import Sum

from fedow_core.models import Asset, Token, Transaction, Configuration, Wallet

# Effets de Transaction.save() sur les soldes : qui credite le receiver / debite le sender.
# Sert a recalculer le solde ATTENDU d'un token (= ce qu'il devrait valoir sans lost-update).
# / Mirrors the token effects of Transaction.save() to recompute each token's expected balance.
ACTIONS_CREDIT_RECEIVER = [
    Transaction.SALE, Transaction.QRCODE_SALE, Transaction.REFILL,
    Transaction.FUSION, Transaction.CREATION, Transaction.SUBSCRIBE,
]
ACTIONS_DEBIT_SENDER = [
    Transaction.SALE, Transaction.QRCODE_SALE, Transaction.REFILL,
    Transaction.FUSION, Transaction.REFUND, Transaction.DEPOSIT,
]


class Command(BaseCommand):
    help = (
        "Recale token.value sur la somme reelle des transactions, via des transactions "
        "CORRECTION (append-only, auditable). Dry-run par defaut ; --apply pour ecrire."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Cree les transactions CORRECTION. Sans ce flag : dry-run (aucune ecriture).",
        )
        parser.add_argument(
            "--exclure", nargs="*", default=[],
            help="UUID de wallets a ignorer (ex: client deja regularise hors-bande).",
        )

    def _agreger(self, actions, champ):
        # Somme des montants par (wallet, asset) pour la liste d'actions donnee.
        # / Sum amounts grouped by (wallet, asset) for the given actions.
        lignes = (
            Transaction.objects.filter(action__in=actions)
            .values(champ, "asset").annotate(total=Sum("amount"))
        )
        return {(ligne[champ], ligne["asset"]): ligne["total"] for ligne in lignes}

    def handle(self, *args, **options):
        configuration = Configuration.get_solo()
        wallet_primary_id = configuration.primary_wallet_id
        wallet_primary = configuration.primary_wallet
        wallets_de_lieux = set(
            Wallet.objects.filter(place__isnull=False).values_list("pk", flat=True)
        )
        wallets_exclus = {uuid.replace("-", "") for uuid in options["exclure"]}

        credits_par_token = self._agreger(ACTIONS_CREDIT_RECEIVER, "receiver")
        debits_par_token = self._agreger(ACTIONS_DEBIT_SENDER, "sender")
        remboursements_par_token = self._agreger([Transaction.REFUND], "receiver")

        # On calcule, pour chaque token, l'ecart entre le solde attendu et le solde reel.
        # / Compute the gap between expected and real balance for each token.
        a_corriger = []
        for token in Token.objects.select_related("wallet", "asset", "wallet__place").iterator():
            if str(token.wallet_id).replace("-", "") in wallets_exclus:
                continue
            cle = (token.wallet_id, token.asset_id)
            solde_attendu = (credits_par_token.get(cle) or 0) - (debits_par_token.get(cle) or 0)
            est_un_lieu = token.wallet_id in wallets_de_lieux
            # Le REFUND ne credite le receiver que pour un asset federe, sur un lieu non-primaire.
            if (token.asset.category == Asset.STRIPE_FED_FIAT
                    and est_un_lieu and token.wallet_id != wallet_primary_id):
                solde_attendu += (remboursements_par_token.get(cle) or 0)
            ecart = solde_attendu - token.value
            if ecart != 0:
                a_corriger.append((token, ecart))

        for token, ecart in sorted(a_corriger, key=lambda couple: -abs(couple[1])):
            if token.wallet_id in wallets_de_lieux:
                nom = token.wallet.place.name
            elif token.wallet_id == wallet_primary_id:
                nom = "PRIMARY WALLET"
            else:
                nom = "user:" + str(token.wallet.uuid)[:8]
            self.stdout.write(f"   {ecart / 100:>10.2f} EUR   {token.asset.name:18} {nom}")
        somme_algebrique = sum(ecart for _, ecart in a_corriger) / 100
        self.stdout.write(
            f"=== {len(a_corriger)} tokens a corriger | somme algebrique {somme_algebrique:.2f} EUR ==="
        )

        if not options["apply"]:
            self.stdout.write("DRY-RUN : aucune ecriture. Relancer avec --apply pour creer les CORRECTION.")
            return

        # Creation des CORRECTION UNE PAR UNE (sequentiel => pas de nouveau fork de chaine de hash).
        # / Created one by one (sequential => no new hash-chain fork).
        for token, ecart in a_corriger:
            if ecart > 0:
                # Token sous-compte : on CREDITE le wallet. sender = primaire (pivot), receiver = wallet.
                sender, receiver, montant = wallet_primary, token.wallet, ecart
            else:
                # Token sur-compte : on DEBITE le wallet. sender = wallet, receiver = primaire.
                sender, receiver, montant = token.wallet, wallet_primary, -ecart
            Transaction.objects.create(
                ip="127.0.0.1",
                checkout_stripe=None,
                sender=sender,
                receiver=receiver,
                asset=token.asset,
                amount=montant,
                action=Transaction.CORRECTION,
                card=None,
                primary_card=None,
                comment="Reconciliation drift lost-update (cf TECH_DEV/DRIFT)",
            )
        self.stdout.write(f"OK : {len(a_corriger)} transactions CORRECTION creees.")
