# Tests Fedow – Couverture et Statut

Ce document liste les tests unitaires et d’intégration présents dans le projet Fedow, leur statut de fonctionnement, et les tests importants restant à coder.

---

## 1. Tests existants et fonctionnels

### Classe : `FedowTestCase`
- **setUp** : Préparation de l’environnement de test (création de fédération, admin, place, clés, etc.)
- **create_wallet_via_api** : Utilitaire pour créer un wallet utilisateur via l’API (testée indirectement)
- **_post_from_simulated_cashless / _get_from_simulated_cashless** : Utilitaires pour simuler des requêtes cashless

### Classe : `AssetCardTest`
- **setUp** : Préparation d’assets, cartes, etc.
- **testCreateAssetWithoutAPI** : Création d’un asset sans passer par l’API, vérifie la logique de persistence.
- **create_multiple_card** : Génère plusieurs cartes pour un lieu donné.
- **create_asset_with_API** : Création d’un asset via l’API, vérifie la cohérence des données et la persistance.
- **send_new_tokens_to_wallet** : 
  - Remplit des wallets temporaires avec des tokens sur différents assets.
  - Teste la création de wallet utilisateur via l’API, l’association carte/wallet via l’API, et l’envoi de tokens (incluant l’abonnement).
- **get_stripe_checkout_in_charge_primary_asset_api** : Teste la génération d’un checkout Stripe pour un asset principal.
- **test_all** : Test d’intégration global (enchaîne plusieurs scénarios).

### Classe : `APITestHelloWorld`
- **test_helloworld_allow_any** : Vérifie l’accessibilité de l’endpoint `/helloworld/` sans authentification.
- **test_api_and_handshake_signed_message** : Vérifie la signature et la sécurité sur l’API handshake.

### Classe : `HandshakeTest`
- **test_place_and_admin_created** : Vérifie la création correcte d’un lieu et de son admin.
- **test_simulate_cashless_handshake** : Simule un handshake cashless complet, avec vérification des clés et des liens admin.

---

## 2. Tests existants mais non fonctionnels / à corriger

- **send_new_tokens_to_wallet** (dans `AssetCardTest`)  
  _Statut : En erreur actuellement (problème de Wallet non trouvé lors de l’association carte/wallet via l’API)._  
  _Cause probable : souci de persistence ou de récupération du wallet entre deux requêtes de test, ou bug dans la permission côté API._

- **test_all** (dans `AssetCardTest`)  
  _Statut : Peut échouer si un des sous-tests échoue (notamment la partie wallet/card)._  
  _À surveiller lors des corrections._

---

## 3. Tests importants à coder (TODO)

- **Test de l’association carte à un wallet SANS user** (cf. TODO en bas du fichier)  
  _Vérifier que l’API refuse l’association si le wallet n’a pas d’utilisateur associé._

- **Tests de sécurité sur les endpoints sensibles**  
  _Exemple : accès sans signature, avec mauvaise clé, etc. (partiellement couvert mais à compléter)._ 

- **Tests de bout en bout Stripe**  
  _Un test Stripe est commenté, il faudrait le compléter et le rendre effectif._

- **Tests de gestion d’erreur sur la création d’asset/carte/wallet**  
  _Vérifier les cas d’échec, de doublon, de données invalides, etc._

- **Tests de fédération croisée (multi-place, multi-federation)**  
  _Non couverts actuellement._

---

## 4. Notes

- Les tests sont majoritairement d’intégration, certains font appel à la base de données et à des appels API réels (pas de mock).
- La couverture est bonne sur le cycle de vie principal wallet/carte/asset, mais des cas limites et d’erreur restent à fiabiliser.

---

## 5. Diagnostic et résolution d’un bug d’intégration wallet/carte (avril 2025)

### Problème rencontré
- Les tests échouaient lors de l’association d’une carte à un wallet via l’API (`/wallet/linkwallet_cardqrcode/`).
- L’erreur principale était `Wallet.DoesNotExist` côté permission, puis des erreurs de payload (`Ce champ est obligatoire : wallet`).

### Démarche de debug
1. **Ajout de prints détaillés** dans le test et dans la permission `HasWalletSignature` :
   - Affichage de tous les wallets en base juste avant l’appel API.
   - Affichage du payload envoyé à l’API.
   - Affichage de l’UUID recherché côté permission et de tous les wallets existants à ce moment-là.
2. **Constat** : le header `Wallet` n’était pas transmis dans la requête, donc la permission ne trouvait pas le wallet.
3. **Ajout progressif des headers manquants** :
   - `Wallet` : UUID du wallet à associer (dans les headers, pas dans le payload).
   - `Date` : date courante au format ISO (requis par la permission pour vérifier la fraîcheur de la requête).
   - `Signature` : signature du payload, générée avec la clé privée du wallet.
4. **Correction du payload** :
   - Le champ attendu par le serializer était `wallet` (et non `wallet_uuid`).
   - Correction du nom de champ dans le dictionnaire envoyé.
5. **Vérification et relance des tests** : tous les tests passent après ces corrections.

### Bonnes pratiques pour les tests API signés
- Toujours vérifier la documentation du serializer côté API pour les noms exacts des champs attendus.
- Pour les endpoints protégés par signature :
  - Générer la signature du payload avec la clé privée adéquate.
  - Ajouter systématiquement les headers `Signature`, `Wallet`, `Date` dans la requête.
- Ne pas hésiter à ajouter des prints de debug temporaires pour suivre l’état de la base et les headers transmis.

### Exemple de code correct pour un POST signé
```python
from fedow_core.utils import sign_message, data_to_b64, get_private_key
from django.utils.timezone import now

link_data = {
    'wallet': str(wallet.uuid),
    'card_qrcode_uuid': str(card.qrcode_uuid),
}
private_rsa = get_private_key(private_pem)
signature = sign_message(
    data_to_b64(link_data),
    private_rsa,
).decode('utf-8')
response = self.client.post(
    '/wallet/linkwallet_cardqrcode/',
    json.dumps(link_data),
    content_type='application/json',
    headers={
        'Authorization': f'Api-Key {self.temp_key_place}',
        'Wallet': str(wallet.uuid),
        'Date': now().isoformat(),
        'Signature': signature,
    }
)
```

---

**Dernière mise à jour : 2025-04-16**
