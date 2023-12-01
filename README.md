# TiBillet/FEDOW : **FED**erated and **O**pen **W**allet.

> [!WARNING]  
> Work in progress. ALPHA RELEASE.
> Go talk with us !

## Presentation (EN)

[Free and open source software](https://fr.wikipedia.org/wiki/Free/Libre_Open_Source_Software) for cashless payment, creation and management of a
grouping of local, complementary and citizen currencies (MLCC) within a federated network.

_Fedow_ has been designed to connect different [TiBillet/LaBoutik](https://tibillet.org) point-of-sale servers for a place federation.

They can share the NFC / RFID / QRCODE cashless payment and membership cards of their respective users in a open and secure network.

_Fedow_ integrates with [https://tibillet.org tools](https://tibillet.org), it enables the use of dematerialised
wallets (
cashless ), in various community, cooperative and/or commercial venues that can be used directly on the cash register.

_Fedow_ can also be used on its own via a python client or an HTTP API.

It can be used to create a festival cashless system, a loyalty system, a local currency, subscriptions and memberships,
and a badge reader that keeps track of time used for space location, a time clock that tracks time spent, all for one or
more venues.

Finally, Fedow incorporates the principles of [fiat currencies](https://fr.wikipedia.org/wiki/Monnaie_fondante) into a
transparent, non-speculative and energy-efficient blockchain.

You can find out more on our french blog :

[https://codecommun.coop/blog/federation-part5-fedow](https://codecommun.coop/blog/federation-part5-fedow)

## Présentation (FR)

Outil [FLOSS](https://fr.wikipedia.org/wiki/Free/Libre_Open_Source_Software) de création et de gestion d'un groupement
de monnaies locales, complémentaire et citoyenne (MLCC) au sein d'un réseau fédéré,
_Fedow_ a été conçu pour connecter différents serveurs de points de vente TiBillet afin qu'ils puissent partager les
cartes de leurs utilisateurs respectifs.

S'intégrant aux outils [TiBillet](https://tibillet.org) il permet l'utilisation de portefeuilles dématérialisés (
cashless ), dans
différents lieux associatifs, coopératifs et/ou commerciaux directement utilisable sur la caisse enregistreuse.

_Fedow_ peut aussi être utilisé seul via un client python ou une API HTTP.

Il peut être utilisé pour créer un cashless de festival, un système de fidélité, une monnaie locale, des abonnements et
adhésions, une badgeuse qui comptabilise le temps utilisé pour une location d'espace, le tout pour un ou plusieurs
lieux.

Enfin, Fedow intègre des principes de [monnaie fondantes](https://fr.wikipedia.org/wiki/Monnaie_fondante) dans une
chaine de blocs par preuve d'autorité, transparente, non spéculative et non énergivore.

Vous pouvez trouver plus d'informations sur notre blog :

[https://codecommun.coop/blog/federation-part5-fedow](https://codecommun.coop/blog/federation-part5-fedow)

## Features and roadmap

- [x] Handshake with TiBillet/LaBoutik
- [x] Create place
- [x] Create link (or not) with another place
- [x] Hash validation
- [x] Proof of authority (PoA) consensus
- [x] HTTP Signature for transaction auth (rsa asymetrical algorithm)
- [x] Authority delegation for wallet ( user -> place )
- [x] Create fiat asset (ex : euro)
- [x] Create no fiat asset (ex : ticket resto, time currency)
- [x] Create subscription asset (ex : membership)
- [ ] Create time asset (ex : time spent in a place)
- [x] Primary Card authentifier (NFC/RFID)
- [x] Create a new user and new wallet with email or FirstTag of a NFC/RFID card
- [ ] Double authentification
- [x] Transaction Place wallet <-> User wallet
- [x] Transaction Fedow primary wallet (Stripe Connect) <-> User wallet
- [x] Transaction Fedow primary wallet (Stripe Connect) <-> Place wallet
- [ ] Transaction User wallet <-> User wallet via QRCode (need double auth)
- [ ] Transaction Place wallet <-> Place wallet (Compensation algorithm)
- [ ] Webhook
- [x] Wallet on NFC Card (Cashless)
- [ ] Wallet on QRCode (soon, need double auth)
- [x] Refund wallet
- [x] Void card (disconnect card from wallet)
- [x] Scan NFC Card for payment
- [x] Scan NFC Card for subscription
- [x] Scan NFC Card for refill wallet

# Server 

## install

For any help, don't hesitate to join us on [Discord](https://discord.gg/ecb5jtP7vY)
or [Rocket Chat](https://chat.communecter.org/channel/Tibillet)

```bash
# Clone the repo :
git clone https://github.com/TiBillet/Fedow && cd Fedow

# Set your secret :
cp env_example .env && nano .env

# Launch the server :
docker compose up -d

# Logs :
docker compose logs -f 

# Dashboard :
http://localhost:8442/ 
```

## Server usage

Some actions can only be performed on the server itself. The creation of a new federation, a new location and new assets
are all under the control of the network animator.

### Create a new place

```bash
docker compose exec fedow poetry run python manage.py create_place --name "Manapany" --email "admin@manap.org" --description "Manapany Festival Cashless"
```

### Create assets

If you already have a cash register server, cashless and membership [TiBillet/LaBoutik](https://tibillet.org), asset
creation is done automatically during the handshake. Simply enter the key given when creating the location in your
administration interface.

To create assets manually, you'll need the uuid of the place of origin.
arg :

- name : String
- currency_code : String (3 letters)
- origin : String (uuid of the place)
- category : String
    - 'TLF' for local and fiat currency token. (e.g.: Euro equivalent cashless payment system)
    - 'TNF' for local and non fiat currency token. (e.g.: cashless payment system for valuing volunteer work, time
      currency, free cryptocurrency, etc...)
    - 'SUB' for membership or subscription. Can return an additional boolean in the api if the user is up to date.)

```bash
docker compose exec fedow poetry run python manage.py create_asset --name "My local and federated City Currency" --currency_code "MLC" --origin "place.wallet.uuid" --category "TLF"
```

### Create a new federation

A federation brings together assets from different locations so that they can be seen by one another. Example: a common
subscription to access a set of different co-working spaces, a cashless payment system shared between several music
festivals or associations, a shareable time currency, etc...

```bash
docker compose exec fedow poetry run python manage.py create_federation --name "The ESS federation" --description "The federation of social and solidarity-based economy associations."
```

### Add an asset to a federation

Once the federation has been created, you need to add the assets that will be read by all network users, and modifiable
by all network locations, authenticated via their rsa key and signature.

Each location in the federation has delegated authority to modify the assets of each user's wallet. This enables the
asset to be accepted at the location's point of sale.

The location is authenticated via its rsa key, along with its point-of-sale opening manager. Every transaction is
precisely traced.

```bash
docker compose exec fedow poetry run python manage.py add_asset_to_federation --asset_uuid "<asset_uuid>" --federation_uuid "<federation_uuid>"
```

Congratulations, you've created a federation of places around a local, complementary and citizen currency!

# Client

## Python client usage

coming soon

## HTTP API

coming soon


# Test

```bash
poetry shell
coverage run --source='.' manage.py test
coverage report
# or 
coverage html
```

## Made by, with and for :

- [Coopérative Code Commun](https://codecommun.coop)
- [la Réunion des Tiers-lieux](https://www.communecter.org/costum/co/index/slug/LaReunionDesTiersLieux/#welcome)
- [La Raffinerie](https://www.laraffinerie.re/)
- [Communecter](https://www.communecter.org/)
- Le Manapany Festival
- Le Demeter

## Special thanks to :

- [Jetbrain](https://www.jetbrains.com/community/opensource/#support) supports non-commercial open source projects.

## Contact :

- [Discord](https://discord.gg/ecb5jtP7vY)
- [Rocket Chat Tiers Lieux.org](https://chat.tiers-lieux.org/channel/TiBillet)
- [Rocket Chat Communecter](https://chat.communecter.org/channel/Tibillet)
- [mail](mailto:contact@tibillet.re)
