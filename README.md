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


## Principtes

### Assets et Fédération

Une ou plusieurs fédérations peuvent être créées sur un serveur _Fedow_.
Un actif (asset primaire) est créé pour chaque fédération et servira de monnaie d'échange.
Il est lié à un compte Stripe pour une équivalence en euros.

Lors de son arrivée dans une instance _Fedow_, chaque nouveau point de vente génère son propre actif (asset secondaire).
Chaque lieu (ou point de vente) peut être associé à une fédération, et peut choisir d'accepter un ou tous les assets des lieux présents dans la fédération. 

Une balance peut alors être réalisée entre l'asset primaire et les assets secondaires.

## Stripe Connect

Lors de la création d'une instance, un **portefeuille primaire** est créé. 
Ce **portefeuille primaire** est lié à un compte Stripe principal et possède les clés de chiffrements rsa nécéssaires aux transactions sur l'asset primaire.

Lors de la création d'un nouvel espace de point de vente, un compte stripe connect est demandé.
Chaque **portefeuille secondaire** voit alors l'identité de son propriétaire vérifié.

## Mécanismes de compensations entre asset primaire et secondaires.

Est appellé token, asset et **portfeuille primaire** les outils gérés par le serveur _Fedow_ avec une équivalence en **euros** sur le compte stripe principal.

Lors d'une recharque de carte d'un utilisateur en ligne via un paiement stripe, le **portefeuille primaire** est crédité en euros.
C'est une action de création de monnaie.
Le **portefeuille utilisateur** est ensuite crédité en token d'asset **primaire**, une transaction depuis le **portefeuille primaire** vers le **portefeuille utilisateur** est enregistré dans la chaîne de blocs.

Lors d'une recharge en espèces ou carte bancaire via un TPE non géré par _Fedow_, le portefeuille **secondaire** génère un asset **secondaire**.
Le portefeuille **utilisateur** est crédité en token d'asset **secondaire**.
Cet asset **secondaire** est géré directement par le lieu. Ce dernier est responsable financièrement et légalement de sa gestion.

Chaque point de vente peut choisir d'accepter ou non les assets **secondaires** des autres points de vente de la fédération.
Une balance peut être réalisée entre les assets **secondaires** d'un lieu et les tokens d'asset **primaire** du portefeuille **secondaire** d'un autre lieu.

Les portefeuilles **utilisateur** peuvent s'échanger des tokens **primaires** ou **secondaires** entre eux à l'aide de leur signature (chiffrement rsa asymétique).

Les portefeuilles **secondaires** peuvent prélever directement depuis un portefeuille utilisateur si une délégation d'autorité existe.
Exemple : Lors d'une vente d'article, le portefeuille du lieux du point de vente **utilisateur** va prélevé ses tokens **primaire** (monnaie fédérée) depuis le portefeuille **utilisateur**, si une délégation d'autorité existe. 

Ce système peut être comparé aux **Smart Contract** de la blockchain Ethereum. 

Lors d'une opération de balance, le portefeuille point de vente peut échanger ses tokens **primaires** de monnaie fédérée vers le portefeuille **primaire** de l'instance _Fedow_.

Un virement en euros est alors effectué sur le compte Stripe connect du point de vente.

### Délégation d'autorité.

Un mécanisme de délégation d'autorité est disponible sur les *Wallets*.
Un Wallet peut être prélevé automatiquement pour des abonnements, des paiments sans contacts sur des points de ventes Tiillet certifiés ou pour le mécanisme de la monnaie fondante.

On retrouve alors un système similaire aux **Smart Contract** de la blockchain Ethereum.

### Monnaie fondante

Un portefeuille de monnaie fondante est un portefeuille dont le solde diminue de manière régulière. Utile pour :
- Encourager l'économie réèlle
- Prélever des frais de gestion pour la pérennité du système
- Garder l'outil libre et gratuit pour les utilisateurs réguliers et les lieux participants.


### Intégration aux outils TiBillet

Conçu à l'origine pour créer un système de monnaie scripturale en euros ou en temps (tel qu'il est utilisé dans les festivals) pour plusieurs lieux indépendant les uns des autres, le dépôt actuel est une séparation du code source intégré à l'origine dans le [projet de point de vente sans numéraire TiBillet](https://tibillet.org).

> [!INFO]
> Ce projet fait partie des outils coopératifs TiBillet.
> [https://tibillet.org](https://tibillet.org)

Fedow a été conçu pour connecter différents serveurs de points de vente TiBillet afin qu'ils puissent partager les cartes de leurs utilisateurs respectifs.

Stripe connect est actuellement le seul point de paiement accepté pour la gestion des **assets primaires**.

Chaque serveur TiBillet/Caisse connecté à Fedow dispose d'un portefeuille secondaire et d'un identifiant Stripe Connect.

Lorsqu'un achat est effectué dans l'un des points de vente de n'importe quel serveur TiBillet fédéré, un transfert du compte Stripe primaire vers le compte Stripe connect est effectué.

> [!WARNING]  
> Les actifs monétaires primaires et secondaires ne peuvent être créés que si vous avez accès au serveur.
> Il en va de même pour chaque serveur TiBillet. 
> Il n'y a pas d'API pour chacune de ces actions, une opération manuelle est volontairement nécéssaire.

> [!WARNING]
> Chaque clé renvoyée est privée: ne les perdez pas et conservez-les en lieu sûr.
> Elles sont "hachées" du côté du serveur et ne peuvent plus jamais être révélées.

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
poetry run python manage.py new_place --name "Manapany Festival" --email = "contact@manap.org"
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



### API documentation

To create new user wallet and perform transactions, see the OpenAPI documentation :
(work in progress... )

## Contact :

- https://discord.gg/ecb5jtP7vY
- https://chat.tiers-lieux.org/channel/TiBillet
- https://chat.communecter.org/channel/Tibillet

### Sources, veille et inspirations

Sur la supercherie ultra libérale du web3 et des applications décentralisés (Dapp) :
- https://web3isgoinggreat.com/

Sur la monnaie fondante et son auteur : 
- https://fr.wikipedia.org/wiki/Monnaie_fondante
- https://fr.wikipedia.org/wiki/%C3%89conomie_libre

Sur les relations entre consommation, écologie et crypto : 
- https://app.wallabag.it/share/64e5b408043f56.08463016
- https://www.nextinpact.com/article/72029/ia-crypto-monnaie-publicite-chiffrement-lusage-numerique-face-a-son-empreinte-ecologique

Sur les consensus de validation de blockchain :

- https://academy.binance.com/fr/articles/proof-of-authority-explained?hide=stickyBar
- https://github.com/P2Enjoy/proof-of-consensus
- https://www.geeksforgeeks.org/proof-of-stake-pos-in-blockchain/?ref=lbp
- https://www.geeksforgeeks.org/delegated-proof-of-stake/?ref=lbp