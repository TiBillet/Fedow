> [!WARNING]  
> Work in progress. ALPHA RELEASE.

# TiBillet/FEDOW : **FED**erated and **O**pen **W**allet.

## C'est quoi FEDOW ?

Résumé : 

Outil [FLOSS](https://fr.wikipedia.org/wiki/Free/Libre_Open_Source_Software) de création et de gestion d'un groupement de monnaies locales, libre, complémentaire et citoyenne (MLCC) au sein d'un réseau fédéré. 

S'intégrant aux outils [TiBillet](https://tibillet.org) il permet l'utilisation d'une même carte NFC qui porte un portefeuille dématérialisé dans différents lieux associatifs, coopératifs et/ou commerciaux.

Enfin, Fedow intégre des principes de [monnaie fondantes](https://fr.wikipedia.org/wiki/Monnaie_fondante) dans une une chaine de block par preuve d'enjeux, transparente, non spéculative et non énergivore.

## Manifeste pour l'appropriation d'une économie locale, sociale et solidaire.

### Moteur libre et open-source de gestion de monnaies temps et/ou locale.

Parce qu'une banque peut être un logiciel libre :
Nous n'avons pas besoin de blockchain fantaisiste, de NFT, de Dapp ou de tout autre battage techno-solutionniste.

Tout ce dont nous avons besoin, c'est d'un moteur de création monétaire, de gestion de compte et de transactions.
Le tout sous une gestion fédérée et transparente, pour créer des réseaux de points de vente acceptant des monnaies locales, des monnaies temporelles ou même des monnaies qui ne sont pas des monnaies.

Un outil simple pour créer une petite banque à l'échelle d'un petit ou d'un grand territoire et soutenir une économie locale, sociale et inclusive.

### Pourquoi ?

Chez Code Commun (la coopérative numérique qui développe l'écosystème TiBillet), nous pensons que le logiciel libre couplé à des pratiques de gouvernance ouverte et transparente pour une économie sociale et solidaire sont les conditions d'une société appaisée que nous souhaitons voir emmerger.

Avec **Fedow**, qui s'inscrit dans l'écosystème **TiBillet**, nous souhaitons permettre à chacun de créér ou rejoindre une fédéréation de monnaies **locale** ou **temps** et de participer à sa gouvernance.

Nous ne croyons pas aux solutions technologiques promises par le Web3 : Blockchains énergivores, création de valeur sur du vide, bulles spéculatives, marchés d'échanges dérégulés, gourous milliardaires… Autant de promesses populistes d'empuissantements non tenues au service d'une économie ultra-libérale de la rareté et de la spéculation.

Ceci dit, nous ne jetons pas le bébé avec l'eau du bain.

Nous pensons que les entreprises humaines, coopératives et locales peuvent (doivent ?) être soutenues par des outils numériques libres pour construire des structures bancaires locales et coopératives au service d'une économie réelle.

Nous pensons que les technologies de blockchain peuvent aider en garantissant la sécurité, la transparence et la gouvernance partagée : *The code we own is law.*

Nous souhaitons construire **Fedow** dans ce sens : un outil numérique simple et compréhensible par chacun pour une économie **réele, non spéculative, transparente.**


### L'économie réelle et la blockchain éthique

Imaginons un livre de compte tenu par tous les acteurs d'une coopérative.

Dans ce livre de compte, chaque acteur peut créer sa propre monnaie et peut (ou non) l'échanger à un taux fixe avec les autres monnaies de la coopérative.

Une monnaie fédérée à l'ensemble des acteurs est créée, indexée sur l'euro pour que chaque monnaie puisse s'échanger et servir à l'économie rééelle des biens et services.

D'autres type de monnaies non indéxée sur l'euro peuvent être créées : Monnaie temps pour s'échanger des services ou valoriser le bénévolat, monnaie "cadeau" pour analyser les stocks offerts, monnaie "ticket resto" pour gérer des repas collectifs, et même monnaie "libre" compatibles avec d'autres systèmes comme la June.

Couplés au reste des outils de TiBillet, il est alors possible de créer des points de ventes, des caisses enregistreuses, des rapports de comptabilité légaux et des boutiques en ligne qui acceptent indifféramment les monnaies locales et fédérées du réseau, comme des espèces ou cartes bancaires.

Tout ceci avec du matériel DiY et du software low-tech, en favorisant au maximum le re-emploi et le reconditionnement de matériel existant, et en utilisant une preuve d'enjeu comme mécanisme de consensus solide, sécurisé et transparent de validation (cf explications plus bas).


### Financement et pérénisation du projet et lutte contre la spéculation.

Imaginons un mécanisme qui puisse à la fois :

- Inciter de nouveaux acteurs à rejoindre la fédération ou en créer de nouvelles.
- Financer le développement du projet libre et coopératif (Problématique récurrente dans le milieu des logiciels  libres).
- Lutter contre la spéculation et l'accumulation des capitaux pour une économié réelle et non financiarisée.

Une idée a été retenue. Elle à le mérite de résoudre les trois problématiques soulevées et s'inspire fortement de la [monnaie fondante](https://fr.wikipedia.org/wiki/Monnaie_fondante) imaginée par [Silvio Gesell](https://fr.wikipedia.org/wiki/Silvio_Gesell).

#### Concepts :

- Tout le matériel nécéssaire est produit par la coopérative et distribuée à ses acteurs à prix coutant. (logiciel de points de vente, carte RFID, logiciel comptable, e-boutique, etc... voir [TiBillet](https://tibillet.org))
- Chaque utilisateur dispose d'un portefeuille numérique qui lui permet d'utiliser toutes les monnaies du réseau.
- Chaque lieu de point de vente est un **noeud** du réseau et est considéré comme un point de change.
- Les portefeuilles sont utilisables à vie et sans frais pour les utilisateurs ni pour les **noeuds**.
- Un [demeurage](https://fr.wikipedia.org/wiki/Demeurage_(finance)) est appliqué sur les portefeuilles sous la condition suivante : Si la monnaie n'est pas utilisée sous un certain délais, le portefeuille perd de sa valeur: **une partie est prélevée pour être réinjecté dans le réseau coopératif.**


### Je suis un utilisateur lambda, en pratique ça donne quoi ?

- J'adhère et donne de mon temps dans une association de quartier qui utilise TiBillet pour gérer ses adhésions : je reçois une carte de membre et l'association me crédite de la monnaie temps.
- Je peux dépenser cette monnaie temps pour réserver des heures d'utilisation d'un fablab ou d'un espace de travail partagé mis à disposition de l'association dans laquelle j'ai donné mon temps.
- Je scanne ma carte et je peux la recharger en ligne. Je change des euros contre de la monnaie fédérée.
- Je reserve une place dans un festival partenaire de la coopérative qui utilise le système de cashless et de billetterie de TiBillet.
- J'achète le billet, des boissons et de la nourriture sur place avec cette même carte préalablement rechargée : Le festival reçoit de la monnaie fédérée.
- Le festival peut échanger cette monnaie fédérée contre des euros, ou s'en servir pour payer ses prestataires avec tout le bénéfice d'une [monnaie locale complémentaire et citoyenne "MLCC"](https://monnaie-locale-complementaire-citoyenne.net).
- Il me reste de la monnaie sur ma carte. Je peux la dépenser dans un autre lieu qui utilise TiBillet/Fedow ou la garder pour plus tard : Elle est valable à vie.
- Je l'oublie dans un tiroir : Je suis régulièrement rappellé à l'utiliser via les newsletters de la fédération qui font la promotion des évènements associatifs et coopératifs du réseau.
- Au bout d'un an, si je ne me sert toujours plus de ma carte, la fédération récupère une partie l'argent pour le réinjecter dans le développement du réseau.
- La coopérative se réunit régulièrement pour faire le point sur la circulation des monnaies et choisir les projets dans lesquels réinvestir l'argent récupéré.
- Example : 1/3 pour le noeud (organisateur de festival, association...),  1/3 pour un fond commun de soutien aux projets associatifs et coopératifs, 1/3 pour la maintenance et le développement de l'outil.


### Blockchain bas carbone et mécanisme de confiance : La preuve d'enjeux (PoS) : 

Ou comment répondre à la grande question : *Comment faire pour avoir confiance en un système bancaire décentralisé sur lequel repose de l'argent réel ?*


> [!WARNING]  
> Vulgarisation crypto un ptit peu technique !


Pour créer un système décentralisé mais sécurisé et fiduciaire, le Bitcoin à proposé la preuve de travaill : Plus on est nombreux à vérifier, plus il est difficile de falsifier le document comptable car il faut convaincre la majorité pour faire consensus.

Pour encourager le nombre, il est proposé de récompenser les validateurs. Et pour savoir quel validateur va récupérer la récompense, on leur propose une énigme. Celui qui réussi à la résoudre gagne la récompense et valide par la même occasion le bloc de transaction. 

Le reste du groupe vérifie ensuite que ce bloc a bien été validé correctement et tente de résoudre l'énigme suivante. On appelle ça "miner" et cela ne peut se faire qu'à l'aide d'ordinateur trés puissants.

Résultat : c'est super sécurisé car beaucoup de monde vérifie chaque transaction. 

Corollaire : c'est trés (trop) énergivore au point d'en être insoutenable. (Et ne parlons même pas des mécanismes de rareté et de spéculation qui finissent par achever ce système à nos yeux...)

La preuve d'enjeu (Proof of Stake) a été proposée très vite comme une alternative à la preuve de travail (Proof of Work). Dans un système PoS, il n'y a pas de concept de mineurs, de matériel spécialisé ou de consommation massive d'énergie. 

Pour être un validateur, vous devez prouver que vous avez interet à ce que tout le système reste bien valide. Pour ce faire, vous avez simplement à vérouiller une quantité variable de monnaie fédérée que vous récoltez sur un compte séparé.

Dans le PoS, vous ne mettez pas en avant une ressource externe (comme l'électricité ou le matériel), mais une ressource interne : la monnaie fédérée elle même qui n'a pas encore été dépensée par vos usagers.

Cette preuve d'enjeu, c'est la quantité de monnaie fédéré que vous récolterez en installant TiBillet/Fedow. Vous montrez ainsi que vous avez interet à ce que les comptes soient bien valide car vous en possederez une partie des actifs.

Dans un système de chaine de bloc par preuve d'enjeu, il n'y a pas de concept de mineurs, de matériel spécialisé ou de consommation massive d'énergie. Tout ce dont vous avez besoin, c'est d'un PC ordinaire sous linux : chaque serveur hebergeant les solutions TiBillet des lieux de points de vente et d'échange de monnaie est un noeud qui valide les transactions de tout le réseau.

C'est le stock de monnaie fédérée et la transparence des transactions qui créént la confiance.

En pratique : 

- Vous verrouillez une certaine quantitée de fonds de monnaie fédérée dans un portefeuille (ils ne peuvent pas être déplacés pendant que vous validez). 
- Vous vous mettez  d'accord sur l'algorithme Fedow, logiciel libre et auditable, qui valide les transactions avec les autres validateurs du le réseau fédéré.
- Vous validez ainsi chaque transaction et celle des autres, et chacun des participant fait de même. Si tout le monde est d'accord, alors la transaction est validée. Le réseau est alors résilient, immuable et transparent.
- En contre partie de votre participation à la sécurisation du livre de compte commun, vous recevrez une partie des frais prélevés lors de la revalorisation de la monnaie fondante (le [demeurage](https://fr.wikipedia.org/wiki/Demeurage_(finance))) en pourcentage du fond que vous avez bloqué.


Les principes du demeurage et de la monnaie fondante permettent de favoriser la circulation des capitaux. En intégrant ce mécanisme dans le code de **Fedow**, nous tentons d'inciter la création d'un écosystème redistributif, social et solidaire.

Plus vous encouragez vos utilisateurs à utiliser une monnaie locale, plus vous récolterez une partie de la monnaie fondante issu du **demeurage**.

Ce mécanisme propose une solution incitative à la circulation de monnaie(s) locale(s) qui est une grande problèmatique de beaucoup de MLCC (monnaies locales citoyennes et complémentaires).

### C'est quoi la différence finalement avec une autre blockchain ?

Contrairement à la majorité des crypto-actifs, il n'y a pas de **block** fraîchement créés dans le cadre de la récompense pour les validateurs. La monnaie fédérée est émise dans une économie réelle. 

Cette dernière est réalisée par les adhérants et utilisateurs de vos lieux lorsqu'ils échangent de vrai euros pour recharger leur carte cashless de festival ou d'adhésion associative.

La monnaie est bien réelle. Elle n'est pas volatile. Le moteur de l'application et le consensus de validation s'assurent qu'il existe et existera toujours 1€ de disponible en banque pour 1 *token* fédéré.

Nous ne sommes pas une startup. Notre but n'est pas de lever des fonds en crypto-actif ou d'entrer en bourse. Nous ne prélèvons pas de pourcentage sur les transactions dans le but de revendre les tokens que nous créons nous même sur un marché spéculatif.

Nous construisons TiBillet/Fedow au sein de tiers-lieux populaires, d'hackerspace, de coopératives et associations culturelles dans le but de construire des communs.

Nous ne souhaitons pas **un** Fedow pour controler un actif financier, mais **des** Fedows pour des mises en réseaux de lieux.

Nous sommes une société coopérative d'interet commun, et nous invitons tous les acteurs de TiBillet à devenir sociétaires pour décider ensemble de l'évolution du projet.

Nous sommes [CodeCommun.Coop](CodeCommun.Coop), Venez [discuter](https://discord.gg/ecb5jtP7vY) avec nous !

### Project built, financed and tested with the support of :

Originally designed to create a cashless euro or time currency system (as used at festivals) for several venues, the current repository is a separation of the source code originally integrated into the [TiBillet cashless point of sale project](https://tibillet.org).

- [Coopérative Code Commun](https://codecommun.coop)
- [la Réunion des Tiers-lieux](https://www.communecter.org/costum/co/index/slug/LaReunionDesTiersLieux/#welcome)
- [La Raffinerie](https://www.laraffinerie.re/)
- [Communecter](https://www.communecter.org/)
- [Le Bisik](https://bisik.re)
- [Jetbrain](https://www.jetbrains.com/community/opensource/#support) supports non-commercial open source projects.
- Le Manapany Festival
- Le Demeter

## Install

```bash
cp env_example .env
# Edit .env 
docker compose up -d
```

## Development environment

```bash
git pull
poetry install --test # add test for pop database with test data
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

### Sources, veille et inspirations

Sur la supercherie ultra libérale du web3 et des applications décentralisés (Dapp) :
- https://web3isgoinggreat.com/

Sur la monnaie fondante et son auteur : 
- https://fr.wikipedia.org/wiki/Monnaie_fondante
- https://fr.wikipedia.org/wiki/%C3%89conomie_libre

Sur les relations entre consommation, écologie et crypto : 
- https://app.wallabag.it/share/64e5b408043f56.08463016
- https://www.nextinpact.com/article/72029/ia-crypto-monnaie-publicite-chiffrement-lusage-numerique-face-a-son-empreinte-ecologique