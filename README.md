> [!WARNING]  
> Work in progress. ALPHA RELEASE.

# FEDOW : Federated and open wallet.

### Free and open-source engine for time and local currency.

Because a bank can be free software:
You don't need blockchain, NFT, Dapp or any other techno-solutionist hype.

All you need is an engine for money creation, account management and transactions.
All this under federated and transparent management, to create networks of points of sale accepting local currencies,
time currencies or even currencies that are not currencies.

A simple tool for creating a tiny bank on the scale of a small or large area and supporting a local, social and
inclusive economy.
local, social and inclusive economy.

### Context

Originally designed to create a cashless euro or time currency system (as used at festivals) for several venues, the
current repository is a separation of the source code originally integrated into the TiBillet cashless point of sale
project.

Current repository is a separation of the source code initially integrated into the TiBillet cashless point of sale
project (https://tibillet.org).

### Project built, financed and tested with the support of :

- Coopérative Code Commun (https://codecommun.coop)
- la Réunion des Tiers-lieux (https://www.communecter.org/costum/co/index/slug/LaReunionDesTiersLieux/#welcome)
- La Raffinerie (https://www.laraffinerie.re/)
- Communecter (https://www.communecter.org/)
- Pôle régional des musiques actuelles de la Réunion (https://prma-reunion.fr/)

## Install

```bash
cp env_example .env
# Edit .env 
docker compose up -d
```

## Development environment

```bash
git pull
poetry install
poetry run python manage.py migrate
poetry run python manage.py install
poetry run python manage.py runserver
```

## Test

```bash
poetry shell
coverage run --source='.' manage.py test
coverage report
# or 
coverage html
```

## Documentation

This project is a part of the TiBillet Cooperative tools.

https://tibillet.org

Fedow was designed from the outset to connect different TiBillet point-of-sale servers so that they could share the
cards of their respective users.

Stripe connect is currently the accepted payment endpoint.

Each TiBillet server connected to Fedow has a primary wallet and a Stripe Connect id.

When a cashless reload is validated by Fedow, the card is reloaded and the money is available on the primary Stripe
account.

When a purchase is made in one of the points of sale of any federated TiBillet server, a transfer from the primary
Stripe account to the Stripe connect account of the TiBillet server is carried out.

To do this, you need to create a federated main asset, then create an entry for each federated Tibillet server.

> [!WARNING]  
> The primary and federated monetary asset can only be created if you have access to the server.
> The same applies to each TiBillet server. We will call them "Places".
> There is no API for each of these actions.

> [!WARNING]
> Each key returned is private.
> Do not lose them and keep them in a safe place.
> They are hashed on the server side and can never be revealed again.

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
poetry run python manage.py new_place "Manapany Festival"
# Copy the string and paste it to the TiBillet server administration.
```

### API documentation

To create new user wallet and perform transactions, see the OpenAPI documentation :
(work in progress... )

## Contact :

- https://discord.gg/ecb5jtP7vY
- https://chat.tiers-lieux.org/channel/TiBillet
- https://chat.communecter.org/channel/Tibillet