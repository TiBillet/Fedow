# Fedow – Federated & Open Wallet Engine

[![Build Status](https://img.shields.io/github/workflow/status/TiBillet/Fedow/CI)](https://github.com/TiBillet/Fedow/actions)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Chat on Discord](https://img.shields.io/discord/112233445566778899.svg?label=chat&logo=discord)](https://discord.gg/ecb5jtP7vY)

> **TL;DR**: Fedow is an open source federation engine, blockchain and digital wallet, designed to connect cashless payment systems, local currencies, and memberships across multiple venues, festivals, and cooperative networks.

![Fedow dashboard](https://raw.githubusercontent.com/TiBillet/Fedow/main/fedow_dashboard/static/img/img.png)

---

## Table of Contents
- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [TiBillet Ecosystem](#tibillet-ecosystem)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)
- [Contact & Support](#contact--support)

---

## Overview

Fedow is a free/libre open source software (FLOSS) solution for creating and managing groups of local, complementary, and citizen currencies (MLCC) within a federated network. It connects different point-of-sale servers (TiBillet/LaBoutik) to share cashless cards, memberships, and currencies among users in an open, secure, and transparent network.

- **Efficient blockchain**: Proof of Authority (PoA), non-speculative, transaction traceability.
- **Interoperability**: Connects multiple [LaBoutik](https://github.com/TiBillet/LaBoutik) (cash register) and [Lespass](https://github.com/TiBillet/Lespass) (ticketing, memberships) instances.
- **Dematerialized wallets**: Multi-card (NFC, RFID, QRCode), multi-asset (currencies, time, memberships) management.
- **HTTP API and Python client**: Usable standalone or integrated.

Fedow is used for:
- Festival cashless systems
- Loyalty programs
- Local currencies
- Subscriptions and memberships
- Time tracking and badge readers

Learn more: [https://codecommun.coop/blog/federation-part5-fedow](https://codecommun.coop/blog/federation-part5-fedow)

---

## Features

- Venue and network federation
- Secure transactions (RSA, HTTP Signature)
- Wallet and asset management (currencies, time, memberships)
- Stripe integration (payment, refund)
- NFC/RFID/QRCode card management
- Transparent, efficient blockchain (PoA)
- RESTful API
- Management and automation tools (CLI, scripts)

See the detailed roadmap in the main README.

---

## Installation

### Production
See the official documentation: [https://tibillet.org/docs/install/docker_install](https://tibillet.org/docs/install/docker_install)

### Development / Test
```bash
# Clone the repository
$ git clone https://github.com/TiBillet/Fedow && cd Fedow
# Set up your environment
$ cp env_example .env && nano .env
# Launch the server
$ docker compose up -d
# Access the dashboard
$ http://localhost:8442/
```

---

## Usage

Some actions (creating federations, venues, assets) are reserved for the network administrator.

```bash
# Use via Docker Compose or Poetry
$ python manage.py federations [OPTIONS]
$ docker compose exec fedow poetry run python manage.py federations [OPTIONS]
```

---

## TiBillet Ecosystem

Fedow is part of a suite of free and interoperable tools:
- [Lespass](https://github.com/TiBillet/Lespass): Ticketing, memberships, landing pages
- [LaBoutik](https://github.com/TiBillet/LaBoutik): Cash register, cashless, order management

Together, they enable full management of a cooperative network, festival, local currency, or community venue.

---

## Documentation
- [Official documentation](https://tibillet.org)
- [Technical blog](https://codecommun.coop/blog/federation-part5-fedow)

---

## Contributing
Contributions are welcome! Please read the [CONTRIBUTING.md](CONTRIBUTING.md) file (create if missing) for best practices.

---

## License
Fedow is released under the [AGPL v3](LICENSE) license.

---

## Contact & Support
- [Discord](https://discord.gg/ecb5jtP7vY)
- [Rocket Chat](https://chat.communecter.org/channel/Tibillet)
- [Official website](https://tibillet.org)
- [Contact email](mailto:contact@tibillet.re)

---

CC-BY-SA Coopérative Code Commun, TiBillet, and contributors. 2025.
