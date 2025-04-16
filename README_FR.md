# Fedow – Moteur fédéré & portefeuille ouvert

[![Build Status](https://img.shields.io/github/workflow/status/TiBillet/Fedow/CI)](https://github.com/TiBillet/Fedow/actions)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Chat sur Discord](https://img.shields.io/discord/112233445566778899.svg?label=chat&logo=discord)](https://discord.gg/ecb5jtP7vY)

> **TL;DR** : Fedow est un moteur de fédération open source, blockchain et portefeuille numérique, conçu pour connecter des systèmes de paiement cashless, monnaies locales et adhésions entre plusieurs lieux, festivals et réseaux coopératifs.

![Fedow dashboard](https://raw.githubusercontent.com/TiBillet/Fedow/main/fedow_dashboard/static/img/img.png)

---

## Sommaire
- [Présentation](#présentation)
- [Fonctionnalités](#fonctionnalités)
- [Installation](#installation)
- [Utilisation](#utilisation)
- [Écosystème TiBillet](#écosystème-tibillet)
- [Documentation](#documentation)
- [Contribution](#contribution)
- [Licence](#licence)
- [Contact & Support](#contact--support)

---

## Présentation

Fedow est un logiciel libre (FLOSS) destiné à la création et à la gestion de groupements de monnaies locales, complémentaires et citoyennes (MLCC) dans un réseau fédéré. Il permet de connecter différents serveurs de points de vente (TiBillet/LaBoutik) pour partager les cartes cashless, adhésions et monnaies de leurs utilisateurs dans un réseau ouvert, sécurisé et transparent.

- **Blockchain économe** : Preuve d'autorité (PoA), non spéculative, traçabilité des transactions.
- **Interopérabilité** : Connecte plusieurs instances de [LaBoutik](https://github.com/TiBillet/LaBoutik) (caisse cashless) et [Lespass](https://github.com/TiBillet/Lespass) (billetterie, adhésions).
- **Portefeuilles dématérialisés** : Gestion multi-cartes (NFC, RFID, QRCode), multi-actifs (monnaies, temps, adhésions).
- **API HTTP et client Python** : Utilisable en mode autonome ou intégré.

Fedow est utilisé pour :
- Systèmes cashless de festivals
- Programmes de fidélité
- Monnaies locales
- Abonnements et adhésions
- Badgeuses et gestion du temps d’utilisation

En savoir plus : [https://codecommun.coop/blog/federation-part5-fedow](https://codecommun.coop/blog/federation-part5-fedow)

---

## Fonctionnalités

- Fédération de lieux et de réseaux
- Transactions sécurisées (RSA, HTTP Signature)
- Gestion des portefeuilles et des actifs (monnaies, temps, adhésions)
- Intégration Stripe (paiement, remboursement)
- Gestion des cartes NFC/RFID/QRCode
- Blockchain transparente et économe (PoA)
- API RESTful
- Outils de gestion et d’automatisation (CLI, scripts)

Voir la roadmap détaillée dans le README principal.

---

## Installation

### Production
Voir la documentation officielle : [https://tibillet.org/docs/install/docker_install](https://tibillet.org/docs/install/docker_install)

### Développement / Test
```bash
# Clonez le dépôt
$ git clone https://github.com/TiBillet/Fedow && cd Fedow
# Configurez votre environnement
$ cp env_example .env && nano .env
# Lancez le serveur
$ docker compose up -d
# Accédez au dashboard
$ http://localhost:8442/
```

---

## Utilisation

Certaines actions (création de fédération, de lieu, d’actifs) sont réservées à l’animateur réseau.

```bash
# Utilisation via Docker Compose ou Poetry
$ python manage.py federations [OPTIONS]
$ docker compose exec fedow poetry run python manage.py federations [OPTIONS]
```

---

## Écosystème TiBillet

Fedow fait partie d’un ensemble d’outils libres et interopérables :
- [Lespass](https://github.com/TiBillet/Lespass) : Billetterie, adhésions, landing pages
- [LaBoutik](https://github.com/TiBillet/LaBoutik) : Caisse enregistreuse, cashless, gestion de commandes

Ensemble, ils permettent la gestion complète d’un réseau coopératif, d’un festival, d’une monnaie locale ou d’un tiers-lieu.

---

## Documentation
- [Documentation officielle](https://tibillet.org)
- [Blog technique](https://codecommun.coop/blog/federation-part5-fedow)

---

## Contribution
Les contributions sont les bienvenues ! Merci de lire le fichier [CONTRIBUTING.md](CONTRIBUTING.md) (à créer si absent) pour les bonnes pratiques.

---

## Licence
Fedow est publié sous licence [AGPL v3](LICENSE).

---

## Contact & Support
- [Discord](https://discord.gg/ecb5jtP7vY)
- [Rocket Chat](https://chat.communecter.org/channel/Tibillet)
- [Site officiel](https://tibillet.org)
- [Contact email](mailto:contact@tibillet.re)

---

CC-BY-SA Coopérative Code Commun, TiBillet, et les contributeurs. 2025.
