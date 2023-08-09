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

## Context

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

### Create a new asset

> [!WARNING]  
> The currency asset can only be created if you have access to the server. No API for that.
> 
>The function returns a private key. Don't lose it and store it in a safe place. It is encrypted on the server side and
can never be revealed again.

```bash
# Create new asset
# arg1 = Asset name
# arg2 = Asset code
poetry run python manage.py create_asset FedPeakSou FPS
# return the private key.
```

## Contact :

- https://discord.gg/ecb5jtP7vY
- https://chat.tiers-lieux.org/channel/TiBillet
- https://chat.communecter.org/channel/Tibillet