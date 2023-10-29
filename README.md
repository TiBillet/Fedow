> [!WARNING]  
> Work in progress. ALPHA RELEASE.

# TiBillet/FEDOW : **FED**erated and **O**pen **W**allet.

## C'est quoi FEDOW ?

Résumé : 

Outil [FLOSS](https://fr.wikipedia.org/wiki/Free/Libre_Open_Source_Software) de création et de gestion d'un groupement de monnaies locales, complémentaire et citoyenne (MLCC) au sein d'un réseau fédéré, 
_Fedow_ a été conçu pour connecter différents serveurs de points de vente TiBillet afin qu'ils puissent partager les cartes de leurs utilisateurs respectifs.

S'intégrant aux outils [TiBillet](https://tibillet.org) il permet l'utilisation de portefeuilles dématérialisés dans différents lieux associatifs, coopératifs et/ou commerciaux.

Enfin, Fedow intègre des principes de [monnaie fondantes](https://fr.wikipedia.org/wiki/Monnaie_fondante) dans une chaine de blocs par preuve d'autorité, transparente, non spéculative et non énergivore.

Vous pouvez trouver plus d'informations sur notre blog : 

[https://tibillet.org/blog/federation-part5-fedow](https://tibillet.org/blog/federation-part5-fedow)


### Projet construit, financé et testé avec l'aide de :

- [Coopérative Code Commun](https://codecommun.coop)
- [la Réunion des Tiers-lieux](https://www.communecter.org/costum/co/index/slug/LaReunionDesTiersLieux/#welcome)
- [La Raffinerie](https://www.laraffinerie.re/)
- [Communecter](https://www.communecter.org/)
- [Le Bisik](https://bisik.re)
- [Jetbrain](https://www.jetbrains.com/community/opensource/#support) supports non-commercial open source projects.
- Le Manapany Festival
- Le Demeter

## Install

### With docker compose (Production environment)

```bash
cp env_example .env && nano .env # or Vim ? -> edit .env 
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

## Contact :

- https://discord.gg/ecb5jtP7vY
- https://chat.tiers-lieux.org/channel/TiBillet
- https://chat.communecter.org/channel/Tibillet
