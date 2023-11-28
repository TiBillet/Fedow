# TiBillet/FEDOW : **FED**erated and **O**pen **W**allet.

> [!WARNING]  
> Work in progress. ALPHA RELEASE.
> Go talk with us on :
>   [Discord](https://discord.gg/ecb5jtP7vY) / 
>   [Tiers-lieux.org](https://chat.tiers-lieux.org/channel/TiBillet) / 
>   [Communecter](https://chat.communecter.org/channel/Tibillet) /
>   [mail](mailto:contact@tibillet.re) /

## Presentation (EN)

[FLOSS Tool](https://fr.wikipedia.org/wiki/Free/Libre_Open_Source_Software) for the creation and management of a
grouping
of local, complementary and citizen currencies (MLCC) within a federated network,
_Fedow_ has been designed to connect different TiBillet point-of-sale servers so that they can share the cashless
payment cards of their respective users.

_Fedow_ integrates with [https://tibillet.org tools](https://tibillet.org), it enables the use of dematerialised wallets (
cashless ), in various community, cooperative and/or commercial venues that can be used directly on the cash register.

_Fedow_ can also be used on its own via a python client or an HTTP API.

It can be used to create a festival cashless system, a loyalty system, a local currency, subscriptions and memberships,
and a badge reader that keeps track of time used for space location, a time clock that tracks time spent, all for one or more venues.

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
adhésions, une badgeuse qui comptabilise le temps utilisé pour une location d'espace, le tout pour un ou plusieurs lieux.

Enfin, Fedow intègre des principes de [monnaie fondantes](https://fr.wikipedia.org/wiki/Monnaie_fondante) dans une
chaine de blocs par preuve d'autorité, transparente, non spéculative et non énergivore.

Vous pouvez trouver plus d'informations sur notre blog :

[https://codecommun.coop/blog/federation-part5-fedow](https://codecommun.coop/blog/federation-part5-fedow)

## Features and roadmap

- [x] Handshake with TiBillet/LaBoutik
- [x] Create place
- [x] Create link (or not) with another place
- [x] Hash consensus and validation
- [x] Create fiat asset (ex : euro)
- [x] Create no fiat asset (ex : ticket resto, time currency)
- [x] Create subscription asset (ex : membership)
- [x] Create a new user and new wallet with email or FirstTag of a NFC/RFID card
- [ ] Double authentification

## Server install


```bash
# Set your secret :
cp env_example .env && nano .env

# Pull and lauch the server :
docker compose up -d
```

### Without docker compose (Development environment)

```bash
poetry install # or poetry update if you have already installed it.
poetry shell
./manage.py migrate
./manage.py install
./manage.py runserver
```

## Usage

### Create a new asset

```bash
# Create new asset
# arg1 = Asset name
# arg2 = Asset code (len 3 max)
poetry run python manage.py create_asset Peaksu PKS
# return the private key.
```

### Connect a TiBillet server

```bash
# Create new place
poetry run python manage.py new_place
# Copy the string and paste it to the TiBillet server administration.
```

## Test

```bash
poetry shell
coverage run --source='.' manage.py test
coverage report
# or 
coverage html
```

### Made by, with and for :

- [Coopérative Code Commun](https://codecommun.coop)
- [la Réunion des Tiers-lieux](https://www.communecter.org/costum/co/index/slug/LaReunionDesTiersLieux/#welcome)
- [La Raffinerie](https://www.laraffinerie.re/)
- [Communecter](https://www.communecter.org/)
- [Jetbrain](https://www.jetbrains.com/community/opensource/#support) supports non-commercial open source projects.
- Le Manapany Festival
- Le Demeter


## Contact :

- https://discord.gg/ecb5jtP7vY
- https://chat.tiers-lieux.org/channel/TiBillet
- https://chat.communecter.org/channel/Tibillet
