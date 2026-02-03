from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from fedow_core.models import Configuration, Place, Transaction, Asset, Token, Wallet


class Command(BaseCommand):
    help = (
        "Force la création d'une transaction DEPOSIT (remise en banque) pour un lieu, "
        "sans aucune vérification Stripe ni création de CheckoutStripe."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--place",
            type=str,
            help="Identifiant du lieu: UUID ou nom exact. Optionnel si --wallet est fourni.",
        )
        parser.add_argument(
            "--wallet",
            type=str,
            help="UUID du wallet du lieu. Optionnel si --place est fourni.",
        )
        parser.add_argument(
            "--amount",
            type=int,
            required=True,
            help="Montant (en centimes) à déposer. Aucune vérification Stripe ne sera effectuée.",
        )
        parser.add_argument(
            "--ip",
            type=str,
            default="127.0.0.1",
            help="Adresse IP à enregistrer sur la transaction (défaut: 127.0.0.1)",
        )
        parser.add_argument(
            "--comment",
            type=str,
            default=None,
            help="Commentaire optionnel à apposer sur la transaction.",
        )

    def resolve_place_or_wallet(self, place_arg: str | None, wallet_arg: str | None) -> Wallet:
        if not place_arg and not wallet_arg:
            raise CommandError("Vous devez fournir --place (UUID ou nom) ou --wallet (UUID).")

        # Priorité au wallet si fourni
        if wallet_arg:
            try:
                return Wallet.objects.get(uuid=wallet_arg)
            except Exception:
                raise CommandError(f"Wallet introuvable: {wallet_arg}")

        # Sinon, résolution par le lieu
        assert place_arg is not None
        # Tente une résolution par UUID, sinon par nom
        place_obj = None
        try:
            _ = UUID(place_arg)
            place_obj = Place.objects.get(uuid=place_arg)
        except Exception:
            try:
                place_obj = Place.objects.get(name=place_arg)
            except Place.DoesNotExist:
                raise CommandError(f"Lieu introuvable (UUID ou nom): {place_arg}")

        if not getattr(place_obj, "wallet", None):
            raise CommandError(f"Le lieu '{place_obj}' n'a pas de wallet associé.")
        return place_obj.wallet

    def handle(self, *args, **options):
        amount: int = options["amount"]
        ip: str = options["ip"]
        comment: str | None = options["comment"]

        if amount is None or amount <= 0:
            raise CommandError("--amount est requis et doit être un entier strictement positif (en centimes).")

        # Résolution du wallet du lieu
        wallet: Wallet = self.resolve_place_or_wallet(options.get("place"), options.get("wallet"))

        # Récupération du token FED (STRIPE_FED_FIAT) du wallet lieu
        try:
            fed_token: Token = wallet.tokens.get(asset__category=Asset.STRIPE_FED_FIAT)
        except Token.DoesNotExist:
            raise CommandError("Le wallet du lieu ne possède pas de token de catégorie STRIPE_FED_FIAT.")

        # Wallet primaire (receiver)
        config = Configuration.get_solo()
        primary_wallet = config.primary_wallet
        if not primary_wallet:
            raise CommandError("Configuration.primary_wallet n'est pas défini.")

        # Création de la transaction DEPOSIT
        # IMPORTANT: On ne fait AUCUNE vérification Stripe ici et on ne crée PAS de CheckoutStripe.
        # Le modèle appliquera ses propres validations (ex: solde suffisant pour le sender, etc.).
        tx = Transaction.objects.create(
            ip=ip,
            checkout_stripe=None,
            sender=wallet,
            receiver=primary_wallet,
            asset=fed_token.asset,
            amount=amount,
            action=Transaction.DEPOSIT,
            primary_card=None,
            card=None,
            comment=comment,
        )

        self.stdout.write(self.style.SUCCESS(f"Transaction DEPOSIT créée: {tx.uuid} | amount={amount} | asset={fed_token.asset.name}"))
        self.stdout.write(
            self.style.NOTICE(
                f"Sender (place wallet)={wallet.uuid} -> Receiver (primary)={primary_wallet.uuid}"
            )
        )
