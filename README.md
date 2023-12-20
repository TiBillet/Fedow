# TiBillet/FEDOW : **FED**erated and **O**pen **W**allet.

> [!WARNING]  
> Work in progress. ALPHA RELEASE.
> Go talk with us !

## TiBillet/Fedow, FLOSS tools for collaborative finance.

- Part of the [TiBillet Tools](https://tibillet.org)
- Made by [Coopérative Code Commun](https://codecommun.coop)

![dashboard demo image](https://raw.githubusercontent.com/TiBillet/Fedow/main/fedow_dashboard/static/img/img.png)

## Presentation (EN)

[Free and open source software](https://fr.wikipedia.org/wiki/Free/Libre_Open_Source_Software) for cashless payment,
creation and management of a
grouping of local, complementary and citizen currencies (MLCC) within a federated network.

_Fedow_ has been designed to connect different [TiBillet/LaBoutik](https://tibillet.org) point-of-sale servers for a
place federation. it enables the use of dematerialised wallets (cashless ),
in various community, cooperative and/or commercial venues that can be used directly on the cash register.

They can share the NFC / RFID / QRCODE cashless payment and membership cards of their respective users in a open and
secure network.

_Fedow_ can also be used on its own via a python client or an HTTP API.

It can be used to create a festival cashless system, a loyalty system, a local currency, subscriptions and memberships,
and a badge reader that keeps track of time used for space location, a time clock that tracks time spent, all for one or
more venues.

Finally, Fedow incorporates the principles of [melting fiat currencies](https://fr.wikipedia.org/wiki/Monnaie_fondante)
into a
transparent, non-speculative and energy-efficient blockchain.

You can find out more on our french blog :

[https://codecommun.coop/blog/federation-part5-fedow](https://codecommun.coop/blog/federation-part5-fedow)

## Présentation (FR)

Outil [FLOSS](https://fr.wikipedia.org/wiki/Free/Libre_Open_Source_Software) de création et de gestion d'un groupement*
de monnaies locales, complémentaire et citoyenne (MLCC) au sein d'un réseau fédéré,
_Fedow_ a été conçu pour connecter différents serveurs de points de vente TiBillet afin qu'ils puissent partager les
cartes de leurs utilisateurs respectifs.

S'intégrant aux outils [TiBillet](https://tibillet.org) il permet l'utilisation de portefeuilles dématérialisés (
cashless ), dans
différents lieux associatifs, coopératifs et/ou commerciaux directement utilisable sur la caisse enregistreuse.

_Fedow_ peut aussi être utilisé seul via un client python ou une API HTTP.

Il peut être utilisé pour créer un cashless de festival, un système de fidélité, une monnaie locale, des abonnements et
adhésions, une badgeuse qui comptabilise le temps utilisé pour une location d'espace, le tout pour un ou plusieurs
lieux. Avec des cartes NFC / RFID et bientôt avec un simple scan de QRCode.

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

## Install

For any help, don't hesitate to talk with us on [Discord](https://discord.gg/ecb5jtP7vY)
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

# Usage

Some actions can only be performed on the server itself. The creation of a new federation, a new location and new assets
are all under the control of the network animator.

```bash
# Use compose or poetry command like that :
# Inside the poetry shell 
python manage.py federations [OPTIONS]
# Outsite of docker 
docker compose exec fedow poetry run python manage.py federations [OPTIONS]
```

## Create and manage Federations

A federation brings together assets from different locations so that they can be seen by one another. Example: a common
subscription to access a set of different co-working spaces, a cashless payment system shared between several music
festivals or associations, a shareable time currency, etc...

Fedow use the command-line tool of Django for managing federations. It provides several options to add or remove assets
and places from a federation, as well as listing all assets in the database.

### Options

- `--create`: Create a federation. Requires `--name`.
- `--add_asset`: Add an asset to a federation. Requires `--fed_uuid` and `--asset_uuid`.
- `--remove_asset`: Remove an asset from a federation. Requires `--fed_uuid` and `--asset_uuid`.
- `--add_place`: Add a place to a federation. Requires `--fed_uuid` and `--place_uuid`.
- `--remove_place`: Remove a place from a federation. Requires `--fed_uuid` and `--place_uuid`.
- `--fed_uuid`: The UUID of the federation.
- `--asset_uuid`: The UUID of the asset.
- `--place_uuid`: The UUID of the place.
- `--list`: List all assets and federations in the database.

### Examples

```bash
# List all assets and federation in the database:
python manage.py federations --list
# Create a new federation:
python manage.py federations --create --name "My new federation"
# Add an asset to a federation:
python manage.py federations --add_asset --fed_uuid <FEDERATION_UUID> --asset_uuid <ASSET_UUID>
# Remove an asset from a federation:
python manage.py federations --remove_asset --fed_uuid <FEDERATION_UUID> --asset_uuid <ASSET_UUID>
# Add a place to a federation:
python manage.py federations --add_place --fed_uuid <FEDERATION_UUID> --place_uuid <PLACE_UUID>
# Remove a place from a federation:
python manage.py federations --remove_place --fed_uuid <FEDERATION_UUID> --place_uuid <PLACE_UUID>
```

## Create and manage Places

```bash
python manage.py places [OPTIONS]
```

A place is a location that can be part of a federation. It can be a co-working space, a music festival, a shop, a
associative bar...

After creating the place, Fedow gives you a key to make a handshake with the TiBillet/LaBoutik engine.

Enter this key in your admin interface -> federation.

The handshake will automatically link the assets and NFC cards entered in the TiBillet/LaBoutik engine.

Congratulations, these cards will be readable throughout the federation network!

You can then link the location assets created by the TiBillet/Fedow handshake to a federation to share a local currency,
a time currency or subscriptions throughout the federation.

### Options

- `--create`: Create a new place. Requires `--name` and `--email`. Optional `--description` and `--test`.
- `--list`: List all places in the database.
- `--name`: Name of the place.
- `--email`: Email of the admin.
- `--description`: Description of the place.
- `--test`: If provided with "TEST FED", the place will be automatically added to the test federation.

### Examples

```bash
# Create a place:
python manage.py places --create --name <PLACE_NAME> --email <ADMIN_EMAIL> --description <DESCRIPTION>
# List all places in the database:
python manage.py places --list
```

## Create and manage Assets

If you already have a cash register server, cashless and membership [TiBillet/LaBoutik](https://tibillet.org), asset
creation is done automatically during the handshake. Simply enter the key given when creating the location in your
administration interface.

Please note that once the locations and assets have been configured, you must also validate them on the
TiBillet/LaBoutik side.

### Usage

```bash
python manage.py assets [OPTIONS]
```

### Options

- `--list`: List all assets in the database.
- `--create`: Create an asset. Requires `--name`, `--currency_code`, `--category`, and either `--place_origin`
  or `--wallet_origin`.
- `--place_origin`: UUID of the place origin.
- `--wallet_origin`: UUID of the wallet origin.
- `--currency_code`: Currency code (max 3 characters).
- `--name`: Currency name.
- `--category`: Category of the asset. The choices are:
  - `TLF` for token local fiat currency
  - `TNF` for token local non fiat currency (gift card, voucher for a meal, etc ..) 
  - `SUB` for subscription or membership.
  - `TIM` for time tracking, time currency, etc ...
  - `BDG` For badge reader. Track passage of a card.

### Examples

```bash
# Create an asset:
python manage.py assets --create --name <ASSET_NAME> --currency_code <CURRENCY_CODE> --category <CATEGORY> --place_origin <PLACE_ORIGIN_UUID>
# List all assets in the database:
python manage.py assets --list
```

Congratulations, you've created a federation of places around a local, complementary and citizen currency!

## Python lib

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
- [e-mail](mailto:contact@tibillet.re)
