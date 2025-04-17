# Cahier des Charges - Documentation API Fedow

## Introduction

Ce document présente la documentation de l'API Fedow en format FALC (Facile à Lire et à Comprendre). Il explique comment utiliser l'API pour effectuer les opérations suivantes :

1. Créer un nouveau lieu
2. Créer un nouvel Asset (monnaie)
3. Créer un wallet avec un email
4. Recharger un wallet avec un Asset créé
5. Recharger un wallet avec un Asset fédéré Stripe (primary asset)
6. Réaliser une vente d'article
7. Réaliser un remboursement
8. Réaliser une transaction de wallet à wallet

Chaque section contient des exemples en cURL, Python et JavaScript.

## 1. Créer un nouveau lieu

Un lieu est un espace où les utilisateurs peuvent utiliser leurs wallets pour effectuer des transactions.

### Endpoint

```
POST /place/
```

### Paramètres requis

- `place_domain` : Le domaine du lieu (ex: "monlieu.tibillet.localhost")
- `place_name` : Le nom du lieu
- `admin_email` : L'email de l'administrateur du lieu
- `admin_pub_pem` : La clé publique RSA de l'administrateur (minimum 2048 bits)

### Exemple en cURL

```bash
curl -X POST "https://api.fedow.org/place/" \
  -H "Authorization: Api-Key VOTRE_CLE_API" \
  -H "Content-Type: application/json" \
  -d '{
    "place_domain": "monlieu.tibillet.localhost",
    "place_name": "Mon Lieu",
    "admin_email": "admin@monlieu.com",
    "admin_pub_pem": "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...\n-----END PUBLIC KEY-----"
  }'
```

### Exemple en Python

```python
import requests
import json

url = "https://api.fedow.org/place/"
headers = {
    "Authorization": "Api-Key VOTRE_CLE_API",
    "Content-Type": "application/json"
}
data = {
    "place_domain": "monlieu.tibillet.localhost",
    "place_name": "Mon Lieu",
    "admin_email": "admin@monlieu.com",
    "admin_pub_pem": "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...\n-----END PUBLIC KEY-----"
}

response = requests.post(url, headers=headers, data=json.dumps(data))
print(response.json())
```

### Exemple en JavaScript

```javascript
const url = "https://api.fedow.org/place/";
const headers = {
    "Authorization": "Api-Key VOTRE_CLE_API",
    "Content-Type": "application/json"
};
const data = {
    "place_domain": "monlieu.tibillet.localhost",
    "place_name": "Mon Lieu",
    "admin_email": "admin@monlieu.com",
    "admin_pub_pem": "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...\n-----END PUBLIC KEY-----"
};

fetch(url, {
    method: "POST",
    headers: headers,
    body: JSON.stringify(data)
})
.then(response => response.json())
.then(data => console.log(data))
.catch(error => console.error('Erreur:', error));
```

## 2. Créer un nouvel Asset (monnaie)

Un Asset est une monnaie qui peut être utilisée pour effectuer des transactions dans un lieu.

### Endpoint

```
POST /asset/
```

### Paramètres requis

- `name` : Le nom de l'Asset
- `currency_code` : Le code de la monnaie (3 caractères maximum)
- `category` : La catégorie de l'Asset (choix parmi: "FED", "TLF", "TNF", "TIM", "FID", "BDG", "SUB")

### Paramètres optionnels

- `uuid` : L'identifiant unique de l'Asset (généré automatiquement si non fourni)
- `created_at` : La date de création de l'Asset (date actuelle si non fournie)

### Exemple en cURL

```bash
curl -X POST "https://api.fedow.org/asset/" \
  -H "Authorization: Api-Key VOTRE_CLE_API" \
  -H "Signature: VOTRE_SIGNATURE" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Euro Local",
    "currency_code": "ELO",
    "category": "TLF"
  }'
```

### Exemple en Python

```python
import requests
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
import base64

def sign_message(data, private_key):
    # Convertir les données en JSON puis en bytes
    data_bytes = json.dumps(data).encode('utf-8')
    # Encoder en base64
    data_b64 = base64.b64encode(data_bytes)
    # Signer avec la clé privée
    signature = private_key.sign(
        data_b64,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

# Charger la clé privée
with open("private_key.pem", "rb") as key_file:
    private_key = serialization.load_pem_private_key(
        key_file.read(),
        password=None
    )

url = "https://api.fedow.org/asset/"
data = {
    "name": "Euro Local",
    "currency_code": "ELO",
    "category": "TLF"
}

# Générer la signature
signature = sign_message(data, private_key)

headers = {
    "Authorization": "Api-Key VOTRE_CLE_API",
    "Signature": signature,
    "Content-Type": "application/json"
}

response = requests.post(url, headers=headers, data=json.dumps(data))
print(response.json())
```

### Exemple en JavaScript

```javascript
// Fonction pour signer le message (nécessite une bibliothèque de cryptographie)
async function signMessage(data, privateKey) {
    const dataStr = JSON.stringify(data);
    const dataB64 = btoa(dataStr);
    const signature = await window.crypto.subtle.sign(
        {
            name: "RSA-PSS",
            saltLength: 32,
        },
        privateKey,
        new TextEncoder().encode(dataB64)
    );
    return btoa(String.fromCharCode(...new Uint8Array(signature)));
}

// Exemple d'utilisation
async function createAsset() {
    const data = {
        "name": "Euro Local",
        "currency_code": "ELO",
        "category": "TLF"
    };

    // Charger la clé privée (ceci est un exemple, dans un cas réel, vous devriez utiliser une méthode sécurisée)
    const privateKey = await loadPrivateKey(); // Fonction à implémenter

    const signature = await signMessage(data, privateKey);

    const url = "https://api.fedow.org/asset/";
    const headers = {
        "Authorization": "Api-Key VOTRE_CLE_API",
        "Signature": signature,
        "Content-Type": "application/json"
    };

    const response = await fetch(url, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(data)
    });

    const result = await response.json();
    console.log(result);
}

createAsset();
```

## 3. Créer un wallet avec un email

Un wallet est un portefeuille électronique qui permet de stocker des Assets et d'effectuer des transactions.

### Endpoint

```
POST /wallet/get_or_create/
```

### Paramètres requis

- `email` : L'email de l'utilisateur
- `public_pem` : La clé publique RSA de l'utilisateur (minimum 2048 bits)

### Exemple en cURL

```bash
curl -X POST "https://api.fedow.org/wallet/get_or_create/" \
  -H "Authorization: Api-Key VOTRE_CLE_API" \
  -H "Signature: VOTRE_SIGNATURE" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "utilisateur@exemple.com",
    "public_pem": "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...\n-----END PUBLIC KEY-----"
  }'
```

### Exemple en Python

```python
import requests
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
import base64

def sign_message(data, private_key):
    # Convertir les données en JSON puis en bytes
    data_bytes = json.dumps(data).encode('utf-8')
    # Encoder en base64
    data_b64 = base64.b64encode(data_bytes)
    # Signer avec la clé privée
    signature = private_key.sign(
        data_b64,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

# Charger la clé privée
with open("private_key.pem", "rb") as key_file:
    private_key = serialization.load_pem_private_key(
        key_file.read(),
        password=None
    )

# Charger la clé publique
with open("public_key.pem", "rb") as key_file:
    public_key_pem = key_file.read().decode('utf-8')

url = "https://api.fedow.org/wallet/get_or_create/"
data = {
    "email": "utilisateur@exemple.com",
    "public_pem": public_key_pem
}

# Générer la signature
signature = sign_message(data, private_key)

headers = {
    "Authorization": "Api-Key VOTRE_CLE_API",
    "Signature": signature,
    "Content-Type": "application/json"
}

response = requests.post(url, headers=headers, data=json.dumps(data))
print(response.json())
```

### Exemple en JavaScript

```javascript
// Fonction pour signer le message (nécessite une bibliothèque de cryptographie)
async function signMessage(data, privateKey) {
    const dataStr = JSON.stringify(data);
    const dataB64 = btoa(dataStr);
    const signature = await window.crypto.subtle.sign(
        {
            name: "RSA-PSS",
            saltLength: 32,
        },
        privateKey,
        new TextEncoder().encode(dataB64)
    );
    return btoa(String.fromCharCode(...new Uint8Array(signature)));
}

// Exemple d'utilisation
async function createWallet() {
    // Charger la clé privée et publique (ceci est un exemple, dans un cas réel, vous devriez utiliser une méthode sécurisée)
    const privateKey = await loadPrivateKey(); // Fonction à implémenter
    const publicKeyPem = await loadPublicKeyPem(); // Fonction à implémenter

    const data = {
        "email": "utilisateur@exemple.com",
        "public_pem": publicKeyPem
    };

    const signature = await signMessage(data, privateKey);

    const url = "https://api.fedow.org/wallet/get_or_create/";
    const headers = {
        "Authorization": "Api-Key VOTRE_CLE_API",
        "Signature": signature,
        "Content-Type": "application/json"
    };

    const response = await fetch(url, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(data)
    });

    const result = await response.json();
    console.log(result);
}

createWallet();
```

## 4. Recharger un wallet avec un Asset créé

Cette opération permet de recharger un wallet avec un Asset créé localement.

### Endpoint

```
POST /transaction/
```

### Paramètres requis

- `amount` : Le montant à recharger (en centimes)
- `sender` : L'UUID du wallet du lieu (émetteur)
- `receiver` : L'UUID du wallet de l'utilisateur (récepteur)
- `asset` : L'UUID de l'Asset à utiliser
- `user_card_firstTagId` : L'identifiant de la carte de l'utilisateur
- `primary_card_fisrtTagId` : L'identifiant de la carte primaire du lieu

### Exemple en cURL

```bash
curl -X POST "https://api.fedow.org/transaction/" \
  -H "Authorization: Api-Key VOTRE_CLE_API" \
  -H "Signature: VOTRE_SIGNATURE" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 1000,
    "sender": "UUID_DU_WALLET_DU_LIEU",
    "receiver": "UUID_DU_WALLET_DE_L_UTILISATEUR",
    "asset": "UUID_DE_L_ASSET",
    "user_card_firstTagId": "ID_CARTE_UTILISATEUR",
    "primary_card_fisrtTagId": "ID_CARTE_PRIMAIRE"
  }'
```

### Exemple en Python

```python
import requests
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
import base64

def sign_message(data, private_key):
    # Convertir les données en JSON puis en bytes
    data_bytes = json.dumps(data).encode('utf-8')
    # Encoder en base64
    data_b64 = base64.b64encode(data_bytes)
    # Signer avec la clé privée
    signature = private_key.sign(
        data_b64,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

# Charger la clé privée
with open("private_key.pem", "rb") as key_file:
    private_key = serialization.load_pem_private_key(
        key_file.read(),
        password=None
    )

url = "https://api.fedow.org/transaction/"
data = {
    "amount": 1000,
    "sender": "UUID_DU_WALLET_DU_LIEU",
    "receiver": "UUID_DU_WALLET_DE_L_UTILISATEUR",
    "asset": "UUID_DE_L_ASSET",
    "user_card_firstTagId": "ID_CARTE_UTILISATEUR",
    "primary_card_fisrtTagId": "ID_CARTE_PRIMAIRE"
}

# Générer la signature
signature = sign_message(data, private_key)

headers = {
    "Authorization": "Api-Key VOTRE_CLE_API",
    "Signature": signature,
    "Content-Type": "application/json"
}

response = requests.post(url, headers=headers, data=json.dumps(data))
print(response.json())
```

### Exemple en JavaScript

```javascript
// Fonction pour signer le message (nécessite une bibliothèque de cryptographie)
async function signMessage(data, privateKey) {
    const dataStr = JSON.stringify(data);
    const dataB64 = btoa(dataStr);
    const signature = await window.crypto.subtle.sign(
        {
            name: "RSA-PSS",
            saltLength: 32,
        },
        privateKey,
        new TextEncoder().encode(dataB64)
    );
    return btoa(String.fromCharCode(...new Uint8Array(signature)));
}

// Exemple d'utilisation
async function rechargeWallet() {
    // Charger la clé privée (ceci est un exemple, dans un cas réel, vous devriez utiliser une méthode sécurisée)
    const privateKey = await loadPrivateKey(); // Fonction à implémenter

    const data = {
        "amount": 1000,
        "sender": "UUID_DU_WALLET_DU_LIEU",
        "receiver": "UUID_DU_WALLET_DE_L_UTILISATEUR",
        "asset": "UUID_DE_L_ASSET",
        "user_card_firstTagId": "ID_CARTE_UTILISATEUR",
        "primary_card_fisrtTagId": "ID_CARTE_PRIMAIRE"
    };

    const signature = await signMessage(data, privateKey);

    const url = "https://api.fedow.org/transaction/";
    const headers = {
        "Authorization": "Api-Key VOTRE_CLE_API",
        "Signature": signature,
        "Content-Type": "application/json"
    };

    const response = await fetch(url, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(data)
    });

    const result = await response.json();
    console.log(result);
}

rechargeWallet();
```

## 5. Recharger un wallet avec un Asset fédéré Stripe (primary asset)

Cette opération permet de recharger un wallet avec un Asset fédéré Stripe (primary asset).

### Endpoint

```
POST /wallet/get_federated_token_refill_checkout/
```

### Paramètres requis

- `asset` : L'UUID de l'Asset Stripe fédéré
- `amount` : Le montant à recharger (en centimes)

### Exemple en cURL

```bash
curl -X POST "https://api.fedow.org/wallet/get_federated_token_refill_checkout/" \
  -H "Authorization: Api-Key VOTRE_CLE_API" \
  -H "Wallet: UUID_DU_WALLET_DE_L_UTILISATEUR" \
  -H "Date: 2023-06-01T12:00:00Z" \
  -H "Signature: VOTRE_SIGNATURE" \
  -H "Content-Type: application/json" \
  -d '{
    "asset": "UUID_DE_L_ASSET_STRIPE",
    "amount": 1000
  }'
```

### Exemple en Python

```python
import requests
import json
from datetime import datetime
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
import base64

def sign_message(data, private_key):
    # Convertir les données en JSON puis en bytes
    data_bytes = json.dumps(data).encode('utf-8')
    # Encoder en base64
    data_b64 = base64.b64encode(data_bytes)
    # Signer avec la clé privée
    signature = private_key.sign(
        data_b64,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

# Charger la clé privée
with open("private_key.pem", "rb") as key_file:
    private_key = serialization.load_pem_private_key(
        key_file.read(),
        password=None
    )

url = "https://api.fedow.org/wallet/get_federated_token_refill_checkout/"
data = {
    "asset": "UUID_DE_L_ASSET_STRIPE",
    "amount": 1000
}

# Générer la signature
signature = sign_message(data, private_key)

# Date actuelle au format ISO
date_iso = datetime.now().isoformat()

headers = {
    "Authorization": "Api-Key VOTRE_CLE_API",
    "Wallet": "UUID_DU_WALLET_DE_L_UTILISATEUR",
    "Date": date_iso,
    "Signature": signature,
    "Content-Type": "application/json"
}

response = requests.post(url, headers=headers, data=json.dumps(data))
print(response.json())
```

### Exemple en JavaScript

```javascript
// Fonction pour signer le message (nécessite une bibliothèque de cryptographie)
async function signMessage(data, privateKey) {
    const dataStr = JSON.stringify(data);
    const dataB64 = btoa(dataStr);
    const signature = await window.crypto.subtle.sign(
        {
            name: "RSA-PSS",
            saltLength: 32,
        },
        privateKey,
        new TextEncoder().encode(dataB64)
    );
    return btoa(String.fromCharCode(...new Uint8Array(signature)));
}

// Exemple d'utilisation
async function rechargeWalletWithStripe() {
    // Charger la clé privée (ceci est un exemple, dans un cas réel, vous devriez utiliser une méthode sécurisée)
    const privateKey = await loadPrivateKey(); // Fonction à implémenter

    const data = {
        "asset": "UUID_DE_L_ASSET_STRIPE",
        "amount": 1000
    };

    const signature = await signMessage(data, privateKey);

    // Date actuelle au format ISO
    const dateIso = new Date().toISOString();

    const url = "https://api.fedow.org/wallet/get_federated_token_refill_checkout/";
    const headers = {
        "Authorization": "Api-Key VOTRE_CLE_API",
        "Wallet": "UUID_DU_WALLET_DE_L_UTILISATEUR",
        "Date": dateIso,
        "Signature": signature,
        "Content-Type": "application/json"
    };

    const response = await fetch(url, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(data)
    });

    const result = await response.json();
    console.log(result);
}

rechargeWalletWithStripe();
```

## 6. Réaliser une vente d'article

Cette opération permet de réaliser une vente d'article.

### Endpoint

```
POST /transaction/
```

### Paramètres requis

- `amount` : Le montant de la vente (en centimes)
- `sender` : L'UUID du wallet de l'utilisateur (émetteur)
- `receiver` : L'UUID du wallet du lieu (récepteur)
- `asset` : L'UUID de l'Asset à utiliser
- `user_card_firstTagId` : L'identifiant de la carte de l'utilisateur
- `primary_card_fisrtTagId` : L'identifiant de la carte primaire du lieu

### Exemple en cURL

```bash
curl -X POST "https://api.fedow.org/transaction/" \
  -H "Authorization: Api-Key VOTRE_CLE_API" \
  -H "Signature: VOTRE_SIGNATURE" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 1000,
    "sender": "UUID_DU_WALLET_DE_L_UTILISATEUR",
    "receiver": "UUID_DU_WALLET_DU_LIEU",
    "asset": "UUID_DE_L_ASSET",
    "user_card_firstTagId": "ID_CARTE_UTILISATEUR",
    "primary_card_fisrtTagId": "ID_CARTE_PRIMAIRE"
  }'
```

### Exemple en Python

```python
import requests
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
import base64

def sign_message(data, private_key):
    # Convertir les données en JSON puis en bytes
    data_bytes = json.dumps(data).encode('utf-8')
    # Encoder en base64
    data_b64 = base64.b64encode(data_bytes)
    # Signer avec la clé privée
    signature = private_key.sign(
        data_b64,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

# Charger la clé privée
with open("private_key.pem", "rb") as key_file:
    private_key = serialization.load_pem_private_key(
        key_file.read(),
        password=None
    )

url = "https://api.fedow.org/transaction/"
data = {
    "amount": 1000,
    "sender": "UUID_DU_WALLET_DE_L_UTILISATEUR",
    "receiver": "UUID_DU_WALLET_DU_LIEU",
    "asset": "UUID_DE_L_ASSET",
    "user_card_firstTagId": "ID_CARTE_UTILISATEUR",
    "primary_card_fisrtTagId": "ID_CARTE_PRIMAIRE"
}

# Générer la signature
signature = sign_message(data, private_key)

headers = {
    "Authorization": "Api-Key VOTRE_CLE_API",
    "Signature": signature,
    "Content-Type": "application/json"
}

response = requests.post(url, headers=headers, data=json.dumps(data))
print(response.json())
```

### Exemple en JavaScript

```javascript
// Fonction pour signer le message (nécessite une bibliothèque de cryptographie)
async function signMessage(data, privateKey) {
    const dataStr = JSON.stringify(data);
    const dataB64 = btoa(dataStr);
    const signature = await window.crypto.subtle.sign(
        {
            name: "RSA-PSS",
            saltLength: 32,
        },
        privateKey,
        new TextEncoder().encode(dataB64)
    );
    return btoa(String.fromCharCode(...new Uint8Array(signature)));
}

// Exemple d'utilisation
async function makeSale() {
    // Charger la clé privée (ceci est un exemple, dans un cas réel, vous devriez utiliser une méthode sécurisée)
    const privateKey = await loadPrivateKey(); // Fonction à implémenter

    const data = {
        "amount": 1000,
        "sender": "UUID_DU_WALLET_DE_L_UTILISATEUR",
        "receiver": "UUID_DU_WALLET_DU_LIEU",
        "asset": "UUID_DE_L_ASSET",
        "user_card_firstTagId": "ID_CARTE_UTILISATEUR",
        "primary_card_fisrtTagId": "ID_CARTE_PRIMAIRE"
    };

    const signature = await signMessage(data, privateKey);

    const url = "https://api.fedow.org/transaction/";
    const headers = {
        "Authorization": "Api-Key VOTRE_CLE_API",
        "Signature": signature,
        "Content-Type": "application/json"
    };

    const response = await fetch(url, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(data)
    });

    const result = await response.json();
    console.log(result);
}

makeSale();
```

## 7. Réaliser un remboursement

Cette opération permet de rembourser un client en vidant son wallet d'un Asset spécifique.

### Endpoint

```
POST /card/refund/
```

### Paramètres requis

- `first_tag_id` : L'identifiant de la carte de l'utilisateur à rembourser

### Exemple en cURL

```bash
curl -X POST "https://api.fedow.org/card/refund/" \
  -H "Authorization: Api-Key VOTRE_CLE_API" \
  -H "Signature: VOTRE_SIGNATURE" \
  -H "Content-Type: application/json" \
  -d '{
    "first_tag_id": "ID_CARTE_UTILISATEUR"
  }'
```

### Exemple en Python

```python
import requests
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
import base64

def sign_message(data, private_key):
    # Convertir les données en JSON puis en bytes
    data_bytes = json.dumps(data).encode('utf-8')
    # Encoder en base64
    data_b64 = base64.b64encode(data_bytes)
    # Signer avec la clé privée
    signature = private_key.sign(
        data_b64,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

# Charger la clé privée
with open("private_key.pem", "rb") as key_file:
    private_key = serialization.load_pem_private_key(
        key_file.read(),
        password=None
    )

url = "https://api.fedow.org/card/refund/"
data = {
    "first_tag_id": "ID_CARTE_UTILISATEUR"
}

# Générer la signature
signature = sign_message(data, private_key)

headers = {
    "Authorization": "Api-Key VOTRE_CLE_API",
    "Signature": signature,
    "Content-Type": "application/json"
}

response = requests.post(url, headers=headers, data=json.dumps(data))
print(response.json())
```

### Exemple en JavaScript

```javascript
// Fonction pour signer le message (nécessite une bibliothèque de cryptographie)
async function signMessage(data, privateKey) {
    const dataStr = JSON.stringify(data);
    const dataB64 = btoa(dataStr);
    const signature = await window.crypto.subtle.sign(
        {
            name: "RSA-PSS",
            saltLength: 32,
        },
        privateKey,
        new TextEncoder().encode(dataB64)
    );
    return btoa(String.fromCharCode(...new Uint8Array(signature)));
}

// Exemple d'utilisation
async function refundCard() {
    // Charger la clé privée (ceci est un exemple, dans un cas réel, vous devriez utiliser une méthode sécurisée)
    const privateKey = await loadPrivateKey(); // Fonction à implémenter

    const data = {
        "first_tag_id": "ID_CARTE_UTILISATEUR"
    };

    const signature = await signMessage(data, privateKey);

    const url = "https://api.fedow.org/card/refund/";
    const headers = {
        "Authorization": "Api-Key VOTRE_CLE_API",
        "Signature": signature,
        "Content-Type": "application/json"
    };

    const response = await fetch(url, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(data)
    });

    const result = await response.json();
    console.log(result);
}

refundCard();
```

## 8. Réaliser une transaction de wallet à wallet

Cette opération permet de transférer des tokens directement d'un wallet à un autre.

### Endpoint

```
POST /transaction/
```

### Paramètres requis

- `amount` : Le montant à transférer (en centimes)
- `sender` : L'UUID du wallet émetteur
- `receiver` : L'UUID du wallet récepteur
- `asset` : L'UUID de l'Asset à transférer
- `action` : "TRF" (code pour transfert)

### Paramètres optionnels

- `comment` : Un commentaire sur la transaction
- `metadata` : Des métadonnées supplémentaires au format JSON

### Exemple en cURL

```bash
curl -X POST "https://api.fedow.org/transaction/" \
  -H "Authorization: Api-Key VOTRE_CLE_API" \
  -H "Signature: VOTRE_SIGNATURE" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 1000,
    "sender": "UUID_DU_WALLET_EMETTEUR",
    "receiver": "UUID_DU_WALLET_RECEPTEUR",
    "asset": "UUID_DE_L_ASSET",
    "action": "TRF",
    "comment": "Remboursement déjeuner"
  }'
```

### Exemple en Python

```python
import requests
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
import base64

def sign_message(data, private_key):
    # Convertir les données en JSON puis en bytes
    data_bytes = json.dumps(data).encode('utf-8')
    # Encoder en base64
    data_b64 = base64.b64encode(data_bytes)
    # Signer avec la clé privée
    signature = private_key.sign(
        data_b64,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

# Charger la clé privée
with open("private_key.pem", "rb") as key_file:
    private_key = serialization.load_pem_private_key(
        key_file.read(),
        password=None
    )

url = "https://api.fedow.org/transaction/"
data = {
    "amount": 1000,
    "sender": "UUID_DU_WALLET_EMETTEUR",
    "receiver": "UUID_DU_WALLET_RECEPTEUR",
    "asset": "UUID_DE_L_ASSET",
    "action": "TRF",
    "comment": "Remboursement déjeuner"
}

# Générer la signature
signature = sign_message(data, private_key)

headers = {
    "Authorization": "Api-Key VOTRE_CLE_API",
    "Signature": signature,
    "Content-Type": "application/json"
}

response = requests.post(url, headers=headers, data=json.dumps(data))
print(response.json())
```

### Exemple en JavaScript

```javascript
// Fonction pour signer le message (nécessite une bibliothèque de cryptographie)
async function signMessage(data, privateKey) {
    const dataStr = JSON.stringify(data);
    const dataB64 = btoa(dataStr);
    const signature = await window.crypto.subtle.sign(
        {
            name: "RSA-PSS",
            saltLength: 32,
        },
        privateKey,
        new TextEncoder().encode(dataB64)
    );
    return btoa(String.fromCharCode(...new Uint8Array(signature)));
}

// Exemple d'utilisation
async function transferBetweenWallets() {
    // Charger la clé privée (ceci est un exemple, dans un cas réel, vous devriez utiliser une méthode sécurisée)
    const privateKey = await loadPrivateKey(); // Fonction à implémenter

    const data = {
        "amount": 1000,
        "sender": "UUID_DU_WALLET_EMETTEUR",
        "receiver": "UUID_DU_WALLET_RECEPTEUR",
        "asset": "UUID_DE_L_ASSET",
        "action": "TRF",
        "comment": "Remboursement déjeuner"
    };

    const signature = await signMessage(data, privateKey);

    const url = "https://api.fedow.org/transaction/";
    const headers = {
        "Authorization": "Api-Key VOTRE_CLE_API",
        "Signature": signature,
        "Content-Type": "application/json"
    };

    const response = await fetch(url, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(data)
    });

    const result = await response.json();
    console.log(result);
}

transferBetweenWallets();
```
