import logging
import time
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unicodedata import category
from uuid import UUID

import stripe
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.core.signing import Signer
from django.db.models import Q
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from faker import Faker
from rest_framework import viewsets, status
from rest_framework.decorators import permission_classes, action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from fedow_core.models import Transaction, Place, Configuration, Asset, CheckoutStripe, Token, Wallet, FedowUser, \
    OrganizationAPIKey, Card, Federation, CreatePlaceAPIKey
from fedow_core.permissions import HasKeyAndPlaceSignature, HasAPIKey, IsStripe, CanCreatePlace, \
    HasOrganizationAPIKeyOnly, HasWalletSignature, HasPlaceKeyAndWalletSignature
from fedow_core.serializers import TransactionSerializer, WalletCheckoutSerializer, HandshakeValidator, \
    TransactionW2W, CardSerializer, CardCreateValidator, \
    AssetCreateValidator, OnboardSerializer, AssetSerializer, WalletSerializer, CardRefundOrVoidValidator, \
    FederationSerializer, BadgeCardValidator, WalletGetOrCreate, LinkWalletCardQrCode, BadgeByWalletSignatureValidator, \
    OriginSerializer, CachedTransactionSerializer
from fedow_core.utils import fernet_encrypt, dict_to_b64_utf8, utf8_b64_to_dict, b64_to_data, get_request_ip, \
    get_public_key, rsa_encrypt_string
from fedow_core.validators import PlaceValidator

logger = logging.getLogger(__name__)


def dround(value):
    # Si c'est un entier, on divise par 100
    if type(value) == int:
        return Decimal(value / 100).quantize(Decimal('1.00'))
    return value.quantize(Decimal('1.00'))


def get_api_place_user(request) -> tuple:
    key = request.META["HTTP_AUTHORIZATION"].split()[1]
    api_key = OrganizationAPIKey.objects.get_from_key(key)
    return api_key, api_key.place, api_key.user


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


# Create your views here.
class TestApiKey(viewsets.ViewSet):
    def list(self, request):
        return Response({'message': 'Hello world ApiKey!'})

    def create(self, request):
        # On test ici la permission : HasKeyAndPlaceSignature
        return Response({'message': 'Hello world Signature!'})

    def get_permissions(self):
        permission_classes = [HasAPIKey]
        if self.action in ['create']:
            permission_classes = [HasKeyAndPlaceSignature]
        return [permission() for permission in permission_classes]


class HelloWorld(viewsets.ViewSet):
    """
    GET /heloworld/ : Hello, world!
    """

    def list(self, request):
        return Response({'message': 'Hello world!'})

    def get_permissions(self):
        permission_classes = [AllowAny]
        return [permission() for permission in permission_classes]


#### HTMX PAGE ####


### REST API ###

class AssetAPI(viewsets.ViewSet):
    # def list(self, request):
    #     serializer = AssetSerializer(Asset.objects.all(), many=True)
    #     return Response(serializer.data)

    def create(self, request):
        # Création de l'asset :
        serializer = AssetCreateValidator(data=request.data, context={'request': request})
        if serializer.is_valid():
            # Sérialisation de l'asset
            asset_seralized = AssetSerializer(serializer.asset, context={'request': request})
            return Response(asset_seralized.data, status=status.HTTP_201_CREATED)

        logger.error(f"Asset create error : {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def list(self, request):
        accepted_assets = request.place.accepted_assets()
        serializers = AssetSerializer(accepted_assets, many=True, context={'request': request})
        return Response(serializers.data)

    def retrieve(self, request, pk=None):
        asset = get_object_or_404(Asset, pk=pk)
        # self.action = retrieve -> on ajoute les totaux des token dans la réponse
        serializer = AssetSerializer(asset, context={'request': request, "action": self.action})
        return Response(serializer.data)

    @action(detail=True, methods=['GET'])
    def retrieve_membership_asset(self, request, pk=None):
        # Meme api que RETRIEVE, mais depuis billetterie : c'est une adhésion ou une badgeuse
        asset = get_object_or_404(Asset, pk=pk)
        serializer = AssetSerializer(asset, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['GET'])
    def archive_asset(self, request, pk=None):
        # Seul les place d'origin peuvent archiver
        asset = get_object_or_404(Asset, pk=pk)
        if request.place != asset.place_origin():
            return Response('FORBIDDEN', status=status.HTTP_403_FORBIDDEN)

        asset.archive = True
        asset.save()
        return Response('ARCHIVED', status=status.HTTP_200_OK)

    @action(detail=False, methods=['POST'])
    def create_membership_asset(self, request):
        # Meme api que CREATE, mais depuis billetterie : c'est une adhésion ou une badgeuse
        if not request.data.get('category') in [
            Asset.SUBSCRIPTION,
            Asset.BADGE,
        ]:
            return Response('not a sub asset', status=status.HTTP_400_BAD_REQUEST)
        return self.create(request)

    def get_permissions(self):
        # Pour les routes depuis la billetterie : L'api Key de l'organisation au minimum
        if self.action in ['retrieve_membership_asset', 'create_membership_asset', 'archive_asset']:
            permission_classes = [HasOrganizationAPIKeyOnly]
        else:
            permission_classes = [HasKeyAndPlaceSignature]
        return [permission() for permission in permission_classes]


class CardAPI(viewsets.ViewSet):

    @action(detail=False, methods=['post'])
    def refund(self, request):
        # VOID ou REFUND, on vide la carte des assets non adhésion avec le lieu comme origine
        validator = CardRefundOrVoidValidator(data=request.data, context={'request': request})
        if validator.is_valid():
            refund_data = {
                "serialized_card": CardSerializer(validator.user_card, context={'request': request}).data,
                "before_refund_serialized_wallet": validator.ex_wallet_serialized,
                "serialized_transactions": validator.transactions,
            }
            return Response(refund_data, status=status.HTTP_205_RESET_CONTENT)
        logger.error(f"{timezone.now()} Card update error : {validator.errors}")
        return Response(validator.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def badge(self, request):
        validator = BadgeCardValidator(data=request.data, context={'request': request})
        if validator.is_valid():
            transaction = validator.transaction
            transaction_serialized = TransactionSerializer(transaction, context={'request': request})
            return Response(transaction_serialized.data, status=status.HTTP_201_CREATED)

        logger.error(f"{timezone.now()} Card update error : {validator.errors}")
        return Response(validator.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def set_primary(self, request):
        place: Place = request.place
        card = Card.objects.get(first_tag_id=request.data.get('first_tag_id'))
        if place in card.primary_places.all():
            return Response("Déja OK", status=status.HTTP_208_ALREADY_REPORTED)

        card.primary_places.add(place)
        card.save()
        return Response("OK", status=status.HTTP_200_OK)

    """
    @action(detail=False, methods=['post'])
    def get_checkout(self, request):
        #TODO: A virer, utilisé uniquement dans les tests laboutik
        # Les tests devrait demander via lespass
        if not request.data.get('email'):
            return Response("Email missing", status=status.HTTP_406_NOT_ACCEPTABLE)

        serializer = WalletCheckoutSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            checkout_session = StripeAPI.create_stripe_checkout_for_federated_refill(
                user=serializer.user,
                add_metadata={
                    "card_uuid": f"{serializer.card.uuid}",
                },
            )

            if checkout_session:
                return Response(checkout_session.url, status=status.HTTP_202_ACCEPTED)
            else:
                # Probablement pas de clé API Stripe, on envoie un
                logger.warning(f"get_checkout : No stripe key provided on .env -> 417")
                return Response('Ni stripe key provided', status=status.HTTP_417_EXPECTATION_FAILED)

        logger.error(f"get_checkout error : {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    """


    @action(detail=True, methods=['get'])
    def qr_retrieve(self, request, pk=None):
        # Validator pk est bien un uudi ? :
        qrcode_uuid = UUID(pk)
        card = get_object_or_404(Card, qrcode_uuid=qrcode_uuid)

        # From qr code scan, we just send wallet uuid and is_wallet_ephemere
        # If usr is not created, we ask for the email
        # If the email is not active, we show only the refill button and the recent history
        wallet = card.get_wallet()

        origin_serialized = OriginSerializer(card.origin).data
        data = {
            'wallet_uuid': wallet.uuid,
            'is_wallet_ephemere': card.is_wallet_ephemere(),
            'origin': origin_serialized,
        }
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def retrieve_card_by_signature(self, request):
        # La méthode d'auth diffère d'un retrive standard et donne le wallet plutot que le place
        wallet: Wallet = request.wallet
        cards = wallet.user.cards.all()
        serializer = CardSerializer(cards, context={'request': request}, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def lost_my_card_by_signature(self, request):
        wallet: Wallet = request.wallet
        card = get_object_or_404(Card, user=wallet.user, number_printed=request.data.get('number_printed'))
        card.user = None
        card.wallet_ephemere = None
        card.primary_places.clear()
        card.save()
        return Response('wallet and user detached from card', status=status.HTTP_200_OK)

    def retrieve(self, request, pk=None):
        # Utilisé par les serveurs cashless comme un check card
        try:
            card = Card.objects.get(first_tag_id=pk)
            serializer = CardSerializer(card, context={'request': request})

            logger.info(f"\nCHECK CARTE N° {card.number_printed} - TagId {card.first_tag_id}")
            for token in serializer.data['wallet']['tokens']:
                logger.info(f"Asset {token['asset']['name']} : {dround(token['value'])}\n")

            # import ipdb; ipdb.set_trace()

            return Response(serializer.data, status=status.HTTP_200_OK)
        except Card.DoesNotExist:
            return Response("Carte inconnue", status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"{timezone.now()} Card retrieve error : {e}")
            raise e

    def create(self, request):
        card_serializer = CardCreateValidator(data=request.data, context={'request': request}, many=True)
        if card_serializer.is_valid():
            card_serializer.save()
            logger.info(f"{len(card_serializer.validated_data)} Cards created")
            return Response(f"{len(card_serializer.validated_data)}", status=status.HTTP_201_CREATED,
                            content_type="application/json")

        # Si c'est une erreur de déja créé, on renvoi un statut conflict.
        # trouver qqch de plus élégant ?
        first_error = card_serializer.errors[0]
        if first_error.get('uuid'):
            first_error = first_error['uuid'][0]
            if first_error.code == 'unique':
                logger.warning(f"Card create error : {card_serializer.errors}")
                return Response(card_serializer.errors, status=status.HTTP_409_CONFLICT)

        logger.error(f"Card create error : {card_serializer.errors}")
        return Response(card_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        if self.action in ['qr_retrieve', ]:
            # L'api Key de l'organisation au minimum
            permission_classes = [HasOrganizationAPIKeyOnly]
        elif self.action in ['retrieve_card_by_signature', 'lost_my_card_by_signature']:
            permission_classes = [HasWalletSignature]
        else:
            permission_classes = [HasKeyAndPlaceSignature]
        return [permission() for permission in permission_classes]


class WalletAPI(viewsets.ViewSet):
    """
    GET /wallet/ : liste des wallets
    """
    pagination_class = StandardResultsSetPagination

    ### Route pour LESPAS
    @action(detail=False, methods=['GET'])
    def retrieve_by_signature(self, request):
        # La méthode d'auth diffère d'un retrive standard et donne le wallet plutot que le place
        wallet: Wallet = request.wallet
        serializer = WalletSerializer(wallet, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['POST'])
    def get_federated_token_refill_checkout(self, request):
        # La méthode d'auth diffère d'un retrive standard et donne le wallet plutot que le place
        # Wallet récupéré depuise la permission HasWalletSignature
        wallet: Wallet = request.wallet
        place: Place = request.place

        # On envoie dans les metadata la requete signée du django.
        # La billetterie pourra vérifier que la requete vient bien d'elle.
        lespass_signed_data = f"{request.data.get('lespass_signed_data')}"
        checkout_session = StripeAPI.create_stripe_checkout_for_federated_refill(
            user=wallet.user,
            place=place,
            add_metadata={
                'lespass_signed_data': lespass_signed_data,
                'lespass_uuid': f"{place.uuid}"
            },
        )
        if checkout_session:
            return Response(checkout_session.url, status=status.HTTP_202_ACCEPTED)
        else:
            # Probablement pas de clé API Stripe, on envoie un
            logger.warning(f"get_federated_token_refill_checkout : No stripe key provided on .env -> 417")
            return Response('No stripe key provided', status=status.HTTP_417_EXPECTATION_FAILED)

    @action(detail=True, methods=['GET'])
    def badge(self, request, pk):
        asset = get_object_or_404(Asset, pk=pk, category=Asset.BADGE)
        wallet: Wallet = request.wallet
        place: Place = request.place

        # creation des tokens si premiere fois
        Token.objects.get_or_create(wallet=wallet, asset=asset)
        Token.objects.get_or_create(wallet=place.wallet, asset=asset)

        transaction_dict = {
            "ip": get_request_ip(request),
            "checkout_stripe": None,
            "sender": wallet,
            "receiver": place.wallet,
            "asset": asset,
            "amount": 0,
            "action": Transaction.BADGE,
            "metadata": None,
            "primary_card": None,
            "card": None,
            "subscription_start_datetime": None
        }
        transaction = Transaction.objects.create(**transaction_dict)
        transaction_serialized = TransactionSerializer(transaction, context={'request': request})
        return Response(transaction_serialized.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['GET'])
    def retrieve_from_refill_checkout(self, request, pk=None):
        # Fonction qui vérifie que le paiement a bien eu lieu.
        # A la demande de LesPass

        # Pour la fabrication du checkout, c'est la methode statique StripeAPI : create_stripe_checkout_for_federated_refill
        # TODO: faire un serializer pour verifier checkout.user == user et checkout.place == place
        place = request.place
        wallet = request.wallet
        user = wallet.user

        checkout_db = get_object_or_404(CheckoutStripe, pk=pk)
        logger.warning(f"WEBHOOK GET: {checkout_db.status}")

        # On attend un peu, la vérification est déja en cours par le webhook POST
        now = timezone.now()
        while checkout_db.status == CheckoutStripe.PROGRESS \
                and timezone.now() - now < timedelta(seconds=10):
            time.sleep(1)
            logger.info('checkout db in progress. Waiting for POST ?')
            checkout_db.refresh_from_db()

        if checkout_db.status != CheckoutStripe.PAID:
            # On lance la validation au cas ou le webhook stripe POST ne s'est pas fait
            try:
                checkout_db = StripeAPI.validate_stripe_checkout_and_make_transaction(
                    checkout_db, request)
            except ValueError as e:
                return Response(f"Error validate_stripe_checkout_and_make_transaction : {e}",
                                status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                raise e

        # Paiement validé par le webhook stripe en POST.
        # Go redirection vers Lespass
        if checkout_db.status == CheckoutStripe.PAID:
            logger.warning(f"WEBHOOK GET END: {checkout_db.status}")
            serializer = WalletSerializer(wallet, context={'request': request})
            return Response(serializer.data)

        return Response(f"Checkout Stripe non paid : {checkout_db.status}", status=status.HTTP_402_PAYMENT_REQUIRED)

    @action(detail=False, methods=['POST'])
    def linkwallet_cardqrcode(self, request):

        link_serializer = LinkWalletCardQrCode(data=request.data, context={'request': request})
        if not link_serializer.is_valid():
            logger.error(f"linkwallet_cardqrcode filter(user__isnull=True) : {link_serializer.errors}")
            return Response(link_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        logger.info("FUUUUuuUUSION !")
        card: Card = link_serializer.validated_data['card_qrcode_uuid']

        wallet_source: Wallet = card.get_wallet()
        wallet_target: Wallet = link_serializer.validated_data['wallet']
        if wallet_target.tokens.all().count() > 0 and wallet_target.has_user_card():
            # Pour éviter le vol de compte :
            # si je possède l'email d'une personne, je peux linker son wallet avec une nouvelle carte vierge de ma possession.
            return Response('Wallet conflict : target wallet got a card with tokens.', status=status.HTTP_409_CONFLICT)

        fusionned_card = LinkWalletCardQrCode.fusion(
            card=card,
            wallet_source=wallet_source,
            wallet_target=wallet_target,
            request_obj=request,
        )

        serializer = CardSerializer(fusionned_card, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)



    ### END ROUTE LESPAS

    def retrieve(self, request, pk=None):
        serializer = WalletSerializer(Wallet.objects.get(pk=pk), context={'request': request})
        return Response(serializer.data)

    # def create(self, request):
    #     wallet_create_serializer = WalletCreateSerializer(data=request.data, context={'request': request})
    #     if wallet_create_serializer.is_valid():
    #         wallet_uuid = wallet_create_serializer.data['wallet']
    #         return Response(f"{wallet_uuid}", status=status.HTTP_201_CREATED)
    #
    #     return Response(wallet_create_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['POST'])
    def get_or_create(self, request):
        # Création du wallet avec email et public key
        # En mode get or create -> si existe pas, on fabrique avec le pub
        # Si existe : on vérifie la signature et on envoie le wallet
        wallet_get_or_create_serializer = WalletGetOrCreate(data=request.data, context={'request': request})
        if wallet_get_or_create_serializer.is_valid():
            created: bool = wallet_get_or_create_serializer.created
            user = wallet_get_or_create_serializer.user
            wallet_uuid = user.wallet.uuid

            # get or create ? 200 ou 201
            stt = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            # On ne renvoie que l'uuid. Pour plus d'info, il faudra passer par :
            # retrieve pour le cashless ou retrieve_by_signature pour la billetterie
            return Response(f"{wallet_uuid}", status=stt)

        logger.warning(f"Wallet get_or_create error : {wallet_get_or_create_serializer.errors}")
        return Response(wallet_get_or_create_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        if self.action in [
            'get_or_create', ]:
            # L'api Key de l'organisation au minimum
            permission_classes = [HasOrganizationAPIKeyOnly]
        elif self.action in [
            'retrieve_by_signature',
            'linkwallet_cardqrcode', ]:
            permission_classes = [HasWalletSignature]
        elif self.action in [
            'retrieve_from_refill_checkout',
            'get_federated_token_refill_checkout', 'badge']:
            permission_classes = [HasPlaceKeyAndWalletSignature, ]
        else:
            permission_classes = [HasKeyAndPlaceSignature]
        return [permission() for permission in permission_classes]


class FederationAPI(viewsets.ViewSet):

    def list(self, request):
        place: Place = request.place
        federations = place.federations.all()
        serializer = FederationSerializer(federations, many=True, context={'request': request})
        return Response(serializer.data)

    def get_permissions(self):
        permission_classes = [HasKeyAndPlaceSignature]
        return [permission() for permission in permission_classes]


class PlaceAPI(viewsets.ViewSet):
    """
    GET /place : Places where we can use all federated wallets
    GET /place/<uuid> : Retrieve one place
    POST /place : Create a place where we can use all federated wallets.
    """
    # Déclaration du model principal utilisé pour la vue
    model = Place

    def update(self, request):
        pass

    # Création depuis le moteur Tenant
    def create(self, request):
        validator = PlaceValidator(data=request.data, context={'request': request})
        if validator.is_valid():
            seralized_place = validator.create_place()
            # seralized_place = validator.migrate_place()
            return Response(seralized_place, status=status.HTTP_201_CREATED)
        return Response(validator.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['GET'])
    def link_cashless_to_place(self, request):
        place: Place = request.place
        user = request.wallet.user

        # TODO :A tester :
        if user not in place.admins.all():
            logger.error(f"link_cashless_to_place : {user.email} not an admin email")
            return Response("not an admin email", status=status.HTTP_403_FORBIDDEN)

        # Ne se lance pas lors du premier Flush de Laboutik
        # Les test laboutik on besoin que ce premier flush soit lancé
        # pour vérifier qu'ils ont bien des adhésions et de la monnaie fédérée non stripe
        if place.cashless_server_url is not None:
            if settings.TEST:
                logger.warning("link_cashless_to_place: Laboutik place already conf, "
                               "mais on est en mode test, on écrase. "
                               "On ajoute aussi le cashless de test à la federation de Test")

            else:
                logger.error("link_cashless_to_place: Laboutik place already conf")
                return Response("Laboutik place already conf", status=status.HTTP_405_METHOD_NOT_ALLOWED)

        #### CREATION D'UNE CLE TEMP POUR CASHLESS,
        # même methode que .manage.py place create :
        handshake_cashless_api_key, temp_key = OrganizationAPIKey.objects.create_key(
            name=f"temp_{place.name}:{user.email}",
            place=place,
            user=user,
        )

        admin_pub_key = get_public_key(user.wallet.public_pem)
        rsa_cypher_message = rsa_encrypt_string(utf8_string=temp_key, public_key=admin_pub_key)
        data = {"rsa_cypher_message": rsa_cypher_message}

        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['POST'])
    def handshake(self, request):
        # HANDSHAKE with laboutik server
        # Request only work if came from laboutik server
        # with the right API key gived at the manual creation of new place
        validator = HandshakeValidator(data=request.data, context={'request': request})
        if validator.is_valid():
            validated_data = validator.validated_data

            place: Place = validated_data.get('fedow_place_uuid')
            place.dokos_id = validated_data.get('dokos_id')
            place.cashless_server_ip = validated_data.get('cashless_ip')
            place.cashless_server_url = validated_data.get('cashless_url')
            place.cashless_rsa_pub_key = validated_data.get('cashless_rsa_pub_key')
            place.cashless_admin_apikey = fernet_encrypt(validated_data.get('cashless_admin_apikey'))
            place.save()

            # Create the definitive key for the admin user
            api_key, place_fk, user = get_api_place_user(request)
            if place_fk != place:
                raise Exception("Place not match with the API key")
            # Suppressoin de la clé temporaire
            api_key.delete()

            api_key, key = OrganizationAPIKey.objects.create_key(
                name=f"{place.name}:{user.email}",
                place=place,
                user=user,
            )

            if settings.TEST:
                # Mode test, on ajoute ce nouveau lieu dans la federation de test
                # request.place = place
                self.add_me_to_test_fed(place)

            # Creation du lien Onboard Stripe seulement en prod
            url_onboard = ""
            if not settings.TEST:
                url_onboard = create_account_link_for_onboard(place)

            data = {
                "url_onboard": url_onboard,
                "place_admin_apikey": key,
                "place_wallet_uuid": str(place.wallet.uuid),
                # "place_wallet_public_pem": place.wallet.public_pem,
            }

            data_encoded = dict_to_b64_utf8(data)

            return Response(data_encoded, status=status.HTTP_202_ACCEPTED)
        return Response(validator.errors, status=status.HTTP_400_BAD_REQUEST)

    def add_me_to_test_fed(self, place: Place):
        # import ipdb; ipdb.set_trace()
        if settings.TEST:
            # Récupération du lieu dans le request
            logger.info("Test unitaire en route ! On ajoute dans la fédération de test "
                        "le nouveau lieu créé par les tests de laboutik")

            assets_created_by_the_place = place.wallet.assets_created.all()
            fed_test, created = Federation.objects.get_or_create(name='TEST FED')

            # t'es le flush ou t'es le test ?
            # Si t'as un asset badge, tu es le flush TiBilletistan
            try:
                # On ajoute l'asset principal, créé par un flush normal.
                # Il sera testé dans LaBoutik
                asset_badge = assets_created_by_the_place.get(category=Asset.BADGE)
                asset_adh, asset_abo = assets_created_by_the_place.filter(category=Asset.SUBSCRIPTION)
                fed_test.assets.add(asset_badge)
                fed_test.assets.add(asset_adh)
                fed_test.assets.add(asset_abo)

            except Exception as e:
                logger.info(e)
                # T'as pas de badge, t'es un test, on t'ajoute juste dans la fédé
                # TODO: Ajouter l'asset du premier lieu créé par flush et tester
                # asset_euro = assets_created_by_the_place.get(category=Asset.TOKEN_LOCAL_FIAT)
                # fed_test.assets.add(asset_euro)

            # Que tu sois test ou flush, on t'ajoute
            fed_test.places.add(place)
            # Save pour faire le clear cache
            fed_test.save()
            cache.clear()

            # accepted_assets = request.place.accepted_assets()
            # serializers = AssetSerializer(accepted_assets, many=True, context={'request': request})
            # return Response(serializers.data)
        # return Response('405', status=status.HTTP_405_METHOD_NOT_ALLOWED)

    # noinspection PyTestUnpassedFixture
    def get_permissions(self):
        if self.action == 'handshake':
            permission_classes = [HasAPIKey]
        elif self.action == 'create':
            permission_classes = [CanCreatePlace]
        elif self.action == 'link_cashless_to_place':
            permission_classes = [HasPlaceKeyAndWalletSignature]
        else:
            permission_classes = [HasKeyAndPlaceSignature]
        return [permission() for permission in permission_classes]


# TODO : mettre tout les appel et retour vers stripe dans un view set pour faire une vrai API Stripe X TiBillet
class StripeAPI(viewsets.ViewSet):

    @staticmethod
    def validate_stripe_checkout_and_make_transaction(checkout_db: CheckoutStripe, request):
        checkout_db.status = CheckoutStripe.PROGRESS
        checkout_db.save()
        logger.info(
            f" >>----VALIDATOR---->> StripeAPI : validate_stripe_checkout_and_make_transaction : {checkout_db.status}")
        # Récupération de l'objet checkout chez Stripe
        # En allant chercher directement sur le serveur de stripe, on s'assure de la véracité du checktou
        config = Configuration.get_solo()
        stripe.api_key = config.get_stripe_api()
        checkout = stripe.checkout.Session.retrieve(checkout_db.checkout_session_id_stripe)

        # Vérification de la signature Django et des uuid token par la même occasion.
        signer = Signer()
        signed_data = checkout.metadata.get('signed_data')

        if not signed_data:
            raise ValueError("No signed data on session")

        unsigned_data = utf8_b64_to_dict(signer.unsign(signed_data))

        primary_token = Token.objects.get(uuid=unsigned_data.get('primary_token'))
        user_token = Token.objects.get(uuid=unsigned_data.get('user_token'))

        # is_primary_stripe_token est le token stripe du wallet principal (pas le token stripe d'un wallet user)
        if not primary_token.is_primary_stripe_token():
            raise ValueError("Token not primary")

        card = None
        if unsigned_data.get('card_uuid'):
            card = Card.objects.get(uuid=unsigned_data.get('card_uuid'))
            # L'user du token est-il le même que celui de la carte ?
            if card.user != user_token.wallet.user:
                raise ValueError("card given but user not match")

        # L'asset est-il le même entre les deux tokens ?
        if primary_token.asset != user_token.asset:
            raise ValueError("Asset not match")
            # return Response("Asset not match", status=status.HTTP_409_CONFLICT)

        # Le wallet est il le stripe primaire ?
        if config.primary_wallet != primary_token.wallet:
            raise ValueError("Primary wallet not match")
            # return Response("Primary wallet not match", status=status.HTTP_409_CONFLICT)

        if checkout_db.asset != primary_token.asset:
            raise ValueError("Asset not match in checkout_db")

        if ((checkout.payment_status == 'paid'
             and checkout_db.status == CheckoutStripe.PROGRESS)):
            # Paiement ok ou stripe TEST, on enregistre la transaction
            #     or (settings.STRIPE_TEST and settings.DEBUG)):

            # TODO: Be Atomic -> factorise
            tr_data = {
                'amount': int(checkout.amount_total),
                'sender': f'{primary_token.wallet.uuid}',
                'receiver': f'{user_token.wallet.uuid}',
                'asset': f'{primary_token.asset.uuid}',
                'action': f'{Transaction.REFILL}',
                'metadata': f'{signed_data}',
                'checkout_stripe': f'{checkout_db.uuid}'
            }

            if card:
                # dans le cas d'une recharge par user / wallet sans carte depuis le front billetterie
                tr_data['user_card_uuid'] = f'{card.uuid}'

            transaction_validator = TransactionW2W(data=tr_data, context={'request': request})
            if not transaction_validator.is_valid():
                logger.error(f"TransactionW2W serializer ERROR : {transaction_validator.errors}")
                # Update checkout status
                checkout_db.status = CheckoutStripe.ERROR
                checkout_db.save()
                raise ValidationError(f"TransactionW2W serializer ERROR : {transaction_validator.errors}")

            # Update checkout status
            checkout_db.status = CheckoutStripe.PAID
            # TODO: passer en VALID pour eviter double chargement !!!!!
            checkout_db.save()

        return checkout_db

    # Methode statique car utilisé avant les retours stripe et webhook
    @staticmethod
    def create_stripe_checkout_for_federated_refill(user, add_metadata: dict = None, place=None):
        # Construction du paiement vers stripe
        # Vérifier en POST et en GET, dans les methode de cette même classe

        config = Configuration.get_solo()
        if not config.get_stripe_api():
            return None

        stripe.api_key = config.get_stripe_api()

        # Vérification que l'email soit bien présent pour l'envoyer a Stripe
        email = user.email

        primary_wallet = config.primary_wallet
        stripe_asset = Asset.objects.get(wallet_origin=primary_wallet, category=Asset.STRIPE_FED_FIAT)
        id_price_stripe = stripe_asset.get_id_price_stripe()

        primary_token, created = Token.objects.get_or_create(
            wallet=primary_wallet,
            asset=stripe_asset,
        )

        user_token, created = Token.objects.get_or_create(
            wallet=user.wallet,
            asset=stripe_asset,
        )

        line_items = [{
            "price": f"{id_price_stripe}",
            "quantity": 1
        }]

        metadata = {
            "primary_token": f"{primary_token.uuid}",
            "user_token": f"{user_token.uuid}",
        }

        # Si la requete vient du cashless ou de la carte
        if add_metadata:
            metadata.update(add_metadata)

        signer = Signer()
        signed_data = signer.sign(dict_to_b64_utf8(metadata))

        # Création du checkout Stripe dans la base de donnée
        # status = Created auto
        checkout_db = CheckoutStripe.objects.create(
            asset=user_token.asset,
            user=user,
            metadata=signed_data,
        )

        # La demande a forcément un lesspass url
        # SI ça vient d'un cashless : esce que ça doit vraiment venir d'un cashless sans lespass ?
        # TODO: Oui, si ça vient d'un TPE STRIPE connecté à un pi ou un kiosk
        return_url = f'https://{place.lespass_domain}/my_account/{checkout_db.uuid}/return_refill_wallet/'
        data_checkout = {
            'success_url': f"{return_url}",
            'cancel_url': f"{return_url}",
            'payment_method_types': ["card"],
            'customer_email': f'{email}',
            'line_items': line_items,
            'mode': 'payment',
            'metadata': {
                'signed_data': f'{signed_data}',
            },
            'client_reference_id': f"{user.pk}",
        }

        try:
            checkout_session = stripe.checkout.Session.create(**data_checkout)
        except Exception as e:
            logger.error(f"Creation of Stripe Checkout error : {e}")
            raise Exception("Creation of Stripe Checkout error")

        checkout_db.checkout_session_id_stripe = checkout_session.id
        checkout_db.status = CheckoutStripe.OPEN
        checkout_db.save()

        return checkout_session

    def get_permissions(self):
        permission_classes = [HasOrganizationAPIKeyOnly, ]
        return [permission() for permission in permission_classes]


def create_account_link_for_onboard(place: Place):
    conf = Configuration.get_solo()

    api_key = conf.get_stripe_api()
    if not api_key:
        return ""
    stripe.api_key = api_key

    place.refresh_from_db()
    if not place.stripe_connect_account:
        acc_connect = stripe.Account.create(
            type="standard",
            country="FR",
        )
        id_acc_connect = acc_connect.get('id')
        place.stripe_connect_account = id_acc_connect
        place.save()

    cashless_server_url = place.cashless_server_url

    account_link = stripe.AccountLink.create(
        account=place.stripe_connect_account,
        refresh_url=f"{cashless_server_url}api/onboard_stripe_return/{place.stripe_connect_account}",
        return_url=f"{cashless_server_url}api/onboard_stripe_return/{place.stripe_connect_account}",
        type="account_onboarding",
    )

    url_onboard = account_link.get('url')
    return url_onboard


# TODO: passer dans le StripeAPI
@permission_classes([IsStripe])
class WebhookStripe(APIView):
    def post(self, request):
        # Help STRIPE : https://stripe.com/docs/webhooks/quickstart
        try:
            payload = request.data
            if not payload.get('type') == "checkout.session.completed":
                return Response("Not for me", status=status.HTTP_204_NO_CONTENT)

            # Première vérification du payload envoyé en POST
            # Unsecure car : Never trust user input
            unsecure_checkout = payload['data']['object']
            unsercure_metadata = unsecure_checkout.get('metadata')
            unsecure_signed_data = unsercure_metadata.get('signed_data')
            if not unsecure_signed_data:
                return Response("No signed data on payload", status=status.HTTP_203_NON_AUTHORITATIVE_INFORMATION)
            checkout_session_id_stripe = payload['data']['object']['id']

            checkout_db = get_object_or_404(CheckoutStripe, checkout_session_id_stripe=checkout_session_id_stripe)
            logger.warning(f"Webhook POST : {checkout_db.status}")
            # On attend un peu, la vérification est déja en cours par le webhook POST
            now = timezone.now()
            while checkout_db.status == CheckoutStripe.PROGRESS \
                    and timezone.now() - now < timedelta(seconds=10):
                time.sleep(1)
                logger.info('checkout db in progress. Waiting for GET ?')
                checkout_db.refresh_from_db()

            if checkout_db.status != CheckoutStripe.PAID:

                try:
                    checkout_db = StripeAPI.validate_stripe_checkout_and_make_transaction(
                        checkout_db, request)
                except ValueError as e:
                    return Response(f"Error validate_stripe_checkout_and_make_transaction : {e}",
                                    status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    raise e

                if checkout_db.status == CheckoutStripe.PAID:
                    logger.warning(f"WEBHOOK POST END: {checkout_db.status}")

                    logger.info(
                        f"WebhookStripe 200 OK checkout_db.status {checkout_db.status}")
                    return Response("OK", status=status.HTTP_200_OK)

            logger.warning(
                f"WebhookStripe 208 DEJA TRAITE checkout_db.status {checkout_db.status}")
            return Response("Déja traité", status=status.HTTP_208_ALREADY_REPORTED)


        except Exception as e:
            logger.error(f"WebhookStripe 500 ERROR : {e}")
            return Response("ERROR", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@permission_classes([HasKeyAndPlaceSignature])
class Onboard_stripe_return(APIView):
    def post(self, request):
        onboard_serializer = OnboardSerializer(data=request.data, context={'request': request})
        if onboard_serializer.is_valid():
            info_stripe = onboard_serializer.info_stripe
            details_submitted = info_stripe.get('details_submitted')
            place = onboard_serializer.validated_data.get('fedow_place_uuid')

            if details_submitted:
                logger.info(f"Stripe details_submitted : {details_submitted}")
                # Stripe est OK
                place.stripe_connect_account = onboard_serializer.validated_data.get('id_acc_connect')
                place.stripe_connect_valid = True
                place.save()

                # Mise à jour du cache avec la monnaie fédérée
                place.federated_with()

                # Envoie des infos de la monnaie fédéré
                config = Configuration.get_solo()
                primary_wallet = config.primary_wallet
                primary_stripe_asset = Asset.objects.get(origin=primary_wallet, category=Asset.STRIPE_FED_FIAT)
                if primary_stripe_asset.is_stripe_primary():
                    data = {
                        'primary_stripe_asset_uuid': f'{primary_stripe_asset.uuid}',
                        'primary_stripe_asset_name': primary_stripe_asset.name,
                        'primary_stripe_asset_currency_code': primary_stripe_asset.currency_code,
                    }

                    return Response(data, status=status.HTTP_200_OK)

            # return Response(f"{create_account_link_for_onboard()}", status=status.HTTP_206_PARTIAL_CONTENT)
            place.stripe_connect_valid = False
            place.save()
            logger.error(f"Onboard_stripe_return error : {onboard_serializer.errors}")
        logger.error(f"Onboard_stripe_return : {request.data}")
        return Response("Compte stripe non valide", status=status.HTTP_406_NOT_ACCEPTABLE)


class TransactionAPI(viewsets.ViewSet):
    """
    GET /transaction/ : liste des transactions
    GET /user/transaction/ : transactions avec primary key <uuid>
    """
    pagination_class = StandardResultsSetPagination

    @action(detail=False, methods=['GET'])
    def paginated_list_by_wallet_signature(self, request):
        wallet = request.wallet
        # wallet = sender OR receiver
        transactions = Transaction.objects.filter(Q(sender=wallet) | Q(receiver=wallet))

        # On va récupérer aussi les transactions pour afficher ceux avant une éventuelle fusion
        if transactions.filter(action=Transaction.FUSION).exists():
            ex_wallet = transactions.filter(action=Transaction.FUSION).last().sender
            transactions = Transaction.objects.filter(Q(sender=wallet) | Q(receiver=wallet) |
                                                      Q(sender=ex_wallet) | Q(receiver=ex_wallet))

        # Apply pagination
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(transactions, request)

        # On fabrique un sérializer avec moins d'info que le complet
        # pour l'affichage de la liste des transactions.
        # Moins preneur de ressources
        serializer = CachedTransactionSerializer(page, many=True, context={
            'request': request,
            'detailed_asset': True,
            'serialized_sender': True,
            'serialized_receiver': True,
        })

        # import ipdb; ipdb.set_trace()

        return paginator.get_paginated_response(serializer.data)
        # return Response(serializer.data)



    @action(detail=True, methods=['GET'])
    def badge_with_signature(self, request, pk=None):
        asset = get_object_or_404(Asset, uuid=pk)
        validator = BadgeCardValidator(data=request.data, context={'request': request})
        if validator.is_valid():
            transaction = validator.transaction
            transaction_serialized = TransactionSerializer(transaction, context={'request': request})
            return Response(transaction_serialized.data, status=status.HTTP_201_CREATED)

        logger.error(f"{timezone.now()} Card update error : {validator.errors}")
        return Response(validator.errors, status=status.HTTP_400_BAD_REQUEST)


    def list(self, request):
        serializer = TransactionSerializer(Transaction.objects.all(), many=True, context={'request': request})
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        transaction = get_object_or_404(Transaction, hash=pk)
        serializer = TransactionSerializer(transaction, context={'request': request})
        return Response(serializer.data)

    def create(self, request):
        transaction_validator = TransactionW2W(data=request.data, context={'request': request})
        if transaction_validator.is_valid():
            transaction: Transaction = transaction_validator.transaction
            transaction_serialized = TransactionSerializer(transaction, context={'request': request})
            return Response(transaction_serialized.data, status=status.HTTP_201_CREATED)

        logger.error(f"{timezone.localtime()} ERROR - Transaction create error : {transaction_validator.errors}")
        return Response(transaction_validator.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['POST'])
    def create_membership(self, request):
        # Cela vient de la billetterie. Il nous faut l'api du lieu et la signature du wallet de l'user
        # On vérifie que l'asset soit bien un membership
        get_object_or_404(Asset, category=Asset.SUBSCRIPTION, pk=request.data['asset'])
        if not request.place or not request.wallet:
            return Response('create_membership', status=status.HTTP_400_BAD_REQUEST)

        # Validation préléminaire ok, on lance les vérif de transaction normales
        return self.create(request)

    def get_permissions(self):
        if self.action in ['create_membership', ]:
            permission_classes = [HasPlaceKeyAndWalletSignature]
        elif self.action in [
            'paginated_list_by_wallet_signature',
            'retrieve_badge_with_signature',]:
            permission_classes = [HasWalletSignature]
        elif self.action in ['retrieve', ]:
            permission_classes = [AllowAny]
        else:
            permission_classes = [HasKeyAndPlaceSignature]
        return [permission() for permission in permission_classes]


# Le premier handshake de la billetterie
def root_tibillet_handshake(request):
    if request.method == 'GET':
        ip = get_request_ip(request)
        config = Configuration.get_solo()

        # create_place_apikey -> une seule par instance.
        # DEBUG laisse passer pour test
        if config.create_place_apikey and not settings.DEBUG:
            logger.warning(f"root_tibillet_handshake : {ip} - Already done")
            return JsonResponse({
                "already done": True,
            }, status=status.HTTP_208_ALREADY_REPORTED)

        # La clé pour création de place pour la billetterie.
        # A lancer à la main sur la billetterie : ./manage.py root_fedow
        api_key, key = CreatePlaceAPIKey.objects.create_key(
            name=f"billetterie_root_{ip}",
        )
        config.create_place_apikey = api_key
        config.save()

        return JsonResponse({
            "api_key": key,
            "fedow_pub_pem": config.primary_wallet.public_pem,
        }, status=status.HTTP_201_CREATED)

    raise Http404()


"""
POUR TEST/DEV
"""


# TEST CASHLESS :
def get_new_place_token_for_test(request, name_enc):
    if request.method == 'GET':
        if settings.DEBUG:
            out = StringIO()
            faker = Faker()
            name = b64_to_data(name_enc).get('name')
            if not Federation.objects.filter(name='TEST FED').exists():
                call_command('federations',
                             '--create',
                             '--name', f'TEST FED',
                             stdout=out)

            call_command('places', '--create',
                         '--name', f'{name}',
                         '--email', f'{faker.email()}',
                         stdout=out)
            encoded_data = out.getvalue().split('\n')[-2]
            return JsonResponse({"encoded_data": encoded_data})

    raise Http404()


"""
FIN TEST/DEV
"""
