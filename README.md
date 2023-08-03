# FEDOW : Federated and open wallet

Parce qu'une banque, ça peut être un logiciel libre :
Pas besoin de blockchain, de NFT, de Dapp ou autre hype techno solutionniste.

Il suffit d'un moteur de création monnétaire, de gestion de comptes et de transactions.
Tout ceci en gestion fédérée et transparente, pour créer des réseaux de points de ventes acceptant des monnaies locales,
des monnaies temps ou même des monnaies qui ne sont pas des monnaies.

Un outil simple pour créer une minuscule banque à l'échelle d'un petit ou d'un grand territoire et faire vivre une
économie locale, sociale et solidaire.

## Contexte

Construit à la base pour créer un système de cashless euro ou monnaie temps (comme en festival) pour plusieurs lieux, le
dépot présent est une séparation du code source initialement intégré au projet du point de vente Cashless TiBillet. (https://tibillet.org)

### Projet construit, financé et expériementé avec le soutien de :

- Coopérative Code Commun (https://codecommun.coop)
- la Réunion des Tiers-lieux (https://www.communecter.org/costum/co/index/slug/LaReunionDesTiersLieux/#welcome)
- La Raffinerie (https://www.laraffinerie.re/)
- Communecter (https://www.communecter.org/)
- Pôle régional des musiques actuelles de la Réunion (https://prma-reunion.fr/)

## Installation

```bash
cp env_example .env
# Editer le fichier .env avec vos variables
docker compose up -d
```

## Environnement de developpement

```bash
git pull
poetry install
poetry run python manage.py migrate
poetry run python manage.py runserver
```