# Dérive des soldes de tokens Fedow (lost-update concurrent)

> Investigation menée le **2026-06-09**.
> Asset concerné : **Primary Asset** (`4c0c7c49-b7d8-45e7-9d27-ebf42073667b`, catégorie `FED` / `STRIPE_FED_FIAT`).
> Statut : cause racine prouvée · patch token appliqué · commande `reconcile_tokens` développée et **testée sur copie de prod** (OK, tout retombe à 0) · régularisation prod + virements à lancer.
>
> Exclusion connue : wallet `a750b136-1d7f-4ca2-9808-9f368d39b6d1` (client christelle, +40 €) — déjà remboursé **sur Stripe** (sortie d'argent), donc token 0 correct, à ne PAS corriger (`--exclure`). Reste un drift résiduel +40 € documenté ici, soldé hors-Fedow.

---

## 1. Résumé exécutif (TL;DR)

Le champ **dénormalisé `Token.value`** de Fedow **sous-compte** par rapport à la somme réelle des
transactions du wallet. Cause : `Transaction.save()` met à jour le solde par un **read-modify-write
non atomique et sans verrou** (`token.value += montant` puis `token.save()`). Quand plusieurs
transactions concurrentes touchent le **même token** (cas normal pendant un événement : toutes les
ventes d'un lieu créditent le même wallet, toutes les recharges débitent le wallet primary), des
incréments sont **perdus** (lost update).

Conséquences mesurées sur la prod :

| Catégorie | Montant | Nature |
|---|---|---|
| Lieux sous-payés (fédéré) | **1 262,60 €** | argent réellement encaissé mais non reversé (à régulariser) |
| Client lésé | 40,00 € | une recharge perdue (déjà remboursée hors-bande) |
| Soldes locaux faussés | 98,00 € | monnaies locales (pas de sortie €, incohérence à corriger) |
| Wallet primary | −236,00 € | « monnaie fantôme » : débits `REFILL` perdus à l'émission |

Le **même bug de concurrence** a aussi **forké la chaîne de hash** de l'asset (320 points de fork) —
chantier distinct, voir §6.

LaBoutik (qui compte les `ArticleVendu`, non dénormalisés) est la **source fiable**. La réconciliation
comptable Mama Sound est validée **au centime** entre LaBoutik et Fedow (§8) : l'écart est **uniquement**
dans le `token.value` de Fedow.

---

## 2. Point de départ

Écart constaté entre les deux systèmes pour **Mama Sound**, après un festival (22-24 mai) :

- **Fedow** (admin Asset → ligne « Mama Sound » de *Total by place*) : **31 973,50 €**
- **LaBoutik** (rapport de clôture mensuel, colonne « Fédéré ») : **32 181,00 €**
- Écart apparent : **207,50 €**

Ce 207,50 € s'est révélé **trompeur** : on comparait un **flux** (LaBoutik, les opérations du mois) à
un **stock** (Fedow, un solde de wallet à un instant T). Le `31 973,50` était en fait le **montant de
la remise en banque du 01 juin** (`DEPOSIT`), pas un flux. Le vrai problème était ailleurs et bien
plus grand.

---

## 3. Démarche d'investigation (hypothèses successives)

Important pour la traçabilité : plusieurs pistes ont été **réfutées par les données** avant la bonne.

1. ❌ **« Différence sur les remboursements »** (intuition initiale). Réfutée : les remboursements
   LaBoutik (`VC`/`VV` en `SF`) = les `REFUND` Fedow **au centime, carte par carte** (3 776,70 € sur le festival).
2. ❌ **« Remboursements non propagés à Fedow »** (le code `methode_VC` côté LaBoutik ne teste pas le
   retour de `fedowApi.refund()`). Bug réel mais **non déclenché** ici : tous les remboursements étaient propagés.
3. ❌ **« Ventes non propagées »** (`_send_to_fedow_used_token` saute la propagation sous condition).
   Réfuté : **0 vente** `sync_fedow=False` sur le festival ; ventes LaBoutik = `SALE` Fedow au centime.
4. ✅ **Décomposition flux vs stock** : sur la période, Fedow `SALE`+`REFUND` = LaBoutik = 32 181,00 €
   **exactement**. Le festival est parfaitement réconcilié. L'écart venait du `token.value` lui-même,
   qui ne correspondait pas à la somme de ses transactions.

Élément déclencheur du diagnostic : le **solde reconstruit** (`Σ reçu − Σ envoyé`) du wallet diverge du
`token.value` réel. Cette divergence est la **dérive**.

---

## 4. Cause racine : lost-update dans `Transaction.save()`

Fichier : `fedow_core/models.py`, méthode `Transaction.save()`.

Le solde est maintenu **incrémentalement** : chaque action fait `token.value += / -= montant` **en
mémoire Python**, puis `token.save()` écrit une **valeur absolue** :

```python
token_sender = Token.objects.get(wallet=self.sender, asset=self.asset)      # lecture, sans verrou
token_receiver = Token.objects.get(wallet=self.receiver, asset=self.asset)
...
token_receiver.value += self.amount   # read-modify en mémoire
...
token_receiver.save()                 # write d'une valeur absolue (UPDATE value = <mémoire>)
```

Sous concurrence, deux transactions sur le **même token** se marchent dessus :

```
Caisse A : SELECT value -> lit V          Caisse B : SELECT value -> lit V
A : UPDATE value = V+35                    B : UPDATE value = V+20   (écrase V+35)
```

→ l'incrément de A (35) est **perdu**. Le `token.value` finit **inférieur** à la somme réelle des
transactions. Comme un `UPDATE value = <absolu>` écrit une valeur calculée depuis une **lecture
périmée**, le mode WAL de SQLite (qui sérialise pourtant les écritures) **n'empêche pas** la perte.

Points de contention maximaux :
- **wallet d'un lieu** : reçoit *toutes* ses ventes (`SALE`) → grosse dérive sur les gros lieux.
- **wallet primary** : débité par *toutes* les recharges (`REFILL`) → dérive négative (`-236 €`).

La **dérive est toujours positive** pour les receivers (crédits perdus) et **négative** pour les
senders à forte contention (débits perdus). Elle croît avec le volume de transactions concurrentes.

---

## 5. Preuves

### 5.1 Cas d'école : Grand Gala (le plus simple)

611 ventes le 14-15 mars, cumul des transactions = **10 263,00 €**. Une seule remise en banque le
30 mars de **10 228,00 €** (elle vide le `token.value` réel → donc le token valait 10 228, pas
10 263). **35 € de ventes ont créé leur transaction sans incrémenter le token.** Drift = 35 €.

### 5.2 Corrélation drift ↔ forks de chaîne de hash

Le même mécanisme de concurrence forke aussi la chaîne (§6). La corrélation est **parfaite en rang** :

| Lieu | Drift token | Transactions « nées d'un fork » |
|---|---|---|
| Mama Sound | 1 045,10 € | 279 |
| La Nuit des Fignoss 2025 | 134,00 € | 48 |
| grooveyourass | 48,50 € | 25 |
| Grand Gala | 35,00 € | 8 |

### 5.3 Validation indépendante (SQL brut)

L'audit a été reproduit **au centime** en SQL direct sur une copie de la prod, confirmant les chiffres
calculés via l'ORM Python.

---

## 6. Second bug (distinct) : chaîne de hash forkée

`Transaction._previous_asset_transaction()` renvoie la **dernière transaction de l'asset** (par date).
Deux transactions concurrentes sur le même asset lisent le **même `previous_transaction`** → elles
produisent deux maillons avec le même parent = **fork**. `verify_hash()` ne contrôle que le maillon
*précédent*, pas l'**unicité des enfants** → les forks sont passés inaperçus.

Mesuré sur la prod : **320 points de fork / 643 transactions** sur les 46 127 transactions de l'asset
fédéré, depuis août 2025.

Implication : la « blockchain » Fedow de cet asset **n'est pas linéaire**. C'est un chantier séparé,
plus délicat (on ne « défork » pas sans réécrire les hash en aval) ; le réaliste est d'**empêcher les
futurs forks** (sérialiser l'attribution du `previous_transaction` par asset) et de documenter
l'existant.

---

## 7. Correctif appliqué (patch token)

Contexte stack : **SQLite WAL + Django 4.2**. Donc :
- `select_for_update()` est un **no-op sur SQLite** (inutilisable).
- `transaction_mode: IMMEDIATE` n'existe qu'en Django 5.1+ (indisponible).

Solution retenue : persister le **delta** via une **expression `F()`** (incrément calculé par la base à
l'écriture → atomique, et composé correctement par le WAL), **sans `@transaction.atomic`** — car le
signal `post_save` sur `Transaction` déclenche un `requests.get()` synchrone vers Lespass pour les
`SUBSCRIBE`, qui ne doit pas entrer dans la transaction (risque de blocage + rollback d'adhésion).

Changements dans `fedow_core/models.py` :

```python
# import
from django.db.models import UniqueConstraint, Q, Sum, F

# dans save(), juste après le chargement des tokens :
valeur_du_token_sender_au_chargement = token_sender.value
valeur_du_token_receiver_au_chargement = token_receiver.value

# à la fin, on remplace token_sender.save()/token_receiver.save() par :
delta_du_token_sender = token_sender.value - valeur_du_token_sender_au_chargement
delta_du_token_receiver = token_receiver.value - valeur_du_token_receiver_au_chargement
if delta_du_token_sender != 0:
    Token.objects.filter(pk=token_sender.pk).update(value=F("value") + delta_du_token_sender)
if delta_du_token_receiver != 0:
    Token.objects.filter(pk=token_receiver.pk).update(value=F("value") + delta_du_token_receiver)
```

Propriétés : logique métier et ordre inchangés ; cas `CREATION` (`sender == receiver`) géré
(`delta_sender = 0`, `delta_receiver = +montant`) ; pas de migration. **38 tests `fedow_core` OK**.

⚠️ Limites connues (assumées) : les `assert value >= montant` côté **payeur** restent best-effort sous
concurrence (un double-débit d'une même carte pourrait passer ; n'affecte pas les lieux). Le risque
« token écrit sans transaction si `super().save()` échoue » est **inchangé** par rapport à l'existant.

---

## 8. Réconciliation comptable (méthode + validation)

### 8.1 Solde attendu d'un token (= ce que `token.value` devrait valoir)

D'après la logique exacte de `save()` :

- **crédite le receiver** : `SALE`, `QRCODE_SALE`, `REFILL`, `FUSION`, `CREATION`, `SUBSCRIBE`
- **+ crédite le receiver** pour `REFUND` **uniquement si** asset `FED` **et** wallet de lieu **et** non-primary
- **débite le sender** : `SALE`, `QRCODE_SALE`, `REFILL`, `FUSION`, `REFUND`, `DEPOSIT`
- n'affectent pas le token : `FIRST`, `BADGE`, `TRANSFER`, `VOID`

`drift = attendu − token.value`. Positif = sous-compté (lieux), négatif = sur-compté (primary).

### 8.2 Équation de conservation par lieu

```
Encaissé fédéré  −  Versé en banque  =  Reste dû
```

Validée **au centime** pour Mama Sound (LaBoutik ↔ Fedow), 2026-06-09 :

| | LaBoutik | Fedow |
|---|---|---|
| Encaissé (ventes + remb. sur place) | 112 490,00 | `SAL` 105 003,50 + `RFD` 7 486,50 = 112 490,00 |
| Versé (6 virements Stripe) | 111 431,90 | `BNK` 111 431,90 |
| **Reste dû** | **1 058,10** | **1 058,10** |
| Token Fedow | — | **13,00** |
| **Drift (manque)** | — | **1 045,10** |

Correspondances de modèle :
- encaissé fédéré : LaBoutik `Σ ArticleVendu` en `SF` (`STRIPE_FED`) ↔ Fedow `SAL` + `RFD` reçus
- versements : LaBoutik `ArticleVendu` `article.name = "Stripe TiBillet transfert"`
  (cf `TicketZV4.table_versement_tibillet`) ↔ Fedow `BNK` (`DEPOSIT`), chacun avec un `checkout_stripe`

→ **zéro écart de propagation** : tout l'écart vient du `token.value` dérivé. Mama Sound doit recevoir
**1 058,10 €**, dont **1 045,10 €** perdus par les lost-updates.

---

## 9. Chantiers restants

1. **Régularisation des soldes** (commande `reconcile_tokens`) : matérialiser l'ajustement par une
   **transaction de type `CORRECTION`** (append-only, auditable, et exclue du calcul d'« attendu »
   pour ne pas se neutraliser). Crédite les lieux (drift +), débite le primary (drift −). Le client
   (Christelle) est **exclu** (déjà remboursé). À développer + **tester sur une copie de la DB** avant
   la prod. Décision ouverte : créditer le token seul **(A)** ou créditer puis générer le `DEPOSIT`/
   virement **(B)** pour les lieux.
2. **Chaîne de hash forkée** (§6) : sérialiser l'attribution du `previous_transaction`.
3. **Côté LaBoutik** (non causal ici, mais fragile) : `webview/views.py` `methode_VC` ne teste pas le
   retour de `fedowApi.refund()` et ne pose jamais `sync_fedow` — à fiabiliser.

---

## 10. Annexe — requêtes utiles

### 10.1 Audit du drift par token (Django shell)

```python
from fedow_core.models import Asset, Token, Transaction, Configuration, Wallet
from django.db.models import Sum
CREDIT = [Transaction.SALE, Transaction.QRCODE_SALE, Transaction.REFILL,
          Transaction.FUSION, Transaction.CREATION, Transaction.SUBSCRIBE]
DEBIT  = [Transaction.SALE, Transaction.QRCODE_SALE, Transaction.REFILL,
          Transaction.FUSION, Transaction.REFUND, Transaction.DEPOSIT]
cfg = Configuration.get_solo(); primary_id = cfg.primary_wallet_id
place_ids = set(Wallet.objects.filter(place__isnull=False).values_list("pk", flat=True))
def agg(acts, f):
    return {(r[f], r["asset"]): r["s"] for r in
            Transaction.objects.filter(action__in=acts).values(f, "asset").annotate(s=Sum("amount"))}
credits, debits, refunds = agg(CREDIT, "receiver"), agg(DEBIT, "sender"), agg([Transaction.REFUND], "receiver")
for tok in Token.objects.select_related("wallet", "asset", "wallet__place").iterator():
    k = (tok.wallet_id, tok.asset_id)
    exp = (credits.get(k) or 0) - (debits.get(k) or 0)
    if tok.asset.category == Asset.STRIPE_FED_FIAT and tok.wallet_id in place_ids and tok.wallet_id != primary_id:
        exp += (refunds.get(k) or 0)
    drift = exp - tok.value
    if drift:
        print(round(drift/100, 2), tok.asset.name, getattr(tok.wallet.place, "name", str(tok.wallet.uuid)[:8]))
```

### 10.2 Équivalent SQL brut (sqlite3 — ⚠️ UUID stockés SANS tirets)

```sql
-- Drift par lieu sur l'asset fédéré
WITH credit AS (SELECT receiver_id wid, SUM(amount) v FROM fedow_core_transaction
                WHERE asset_id='4c0c7c49b7d845e79d27ebf42073667b'
                  AND action IN ('SAL','QRS','REF','FUS','CRE','SUB') GROUP BY receiver_id),
     debit  AS (SELECT sender_id wid, SUM(amount) v FROM fedow_core_transaction
                WHERE asset_id='4c0c7c49b7d845e79d27ebf42073667b'
                  AND action IN ('SAL','QRS','REF','FUS','RFD','BNK') GROUP BY sender_id),
     refund AS (SELECT receiver_id wid, SUM(amount) v FROM fedow_core_transaction
                WHERE asset_id='4c0c7c49b7d845e79d27ebf42073667b' AND action='RFD' GROUP BY receiver_id)
SELECT p.name, ROUND((COALESCE(cr.v,0)-COALESCE(d.v,0)+COALESCE(rf.v,0)-tok.value)/100.0,2) drift
FROM fedow_core_token tok
JOIN fedow_core_place p ON p.wallet_id=tok.wallet_id
LEFT JOIN credit cr ON cr.wid=tok.wallet_id
LEFT JOIN debit  d  ON d.wid=tok.wallet_id
LEFT JOIN refund rf ON rf.wid=tok.wallet_id
WHERE tok.asset_id='4c0c7c49b7d845e79d27ebf42073667b'
  AND (COALESCE(cr.v,0)-COALESCE(d.v,0)+COALESCE(rf.v,0)-tok.value) != 0
ORDER BY drift DESC;
```

### 10.3 Détection des forks de chaîne de hash

```sql
-- Parents référencés par plusieurs enfants (hors auto-référence de la FIRST)
SELECT previous_transaction_id, COUNT(*) nb FROM fedow_core_transaction
WHERE asset_id='4c0c7c49b7d845e79d27ebf42073667b' AND uuid != previous_transaction_id
GROUP BY previous_transaction_id HAVING COUNT(*) > 1 ORDER BY nb DESC;
```

### 10.4 Récap comptable d'un lieu (encaissé / versé / reste dû)

```sql
-- Remplacer <WALLET> par le wallet_id du lieu (sans tirets)
SELECT 'encaisse', SUM(amount)/100.0 FROM fedow_core_transaction
  WHERE receiver_id='<WALLET>' AND asset_id='4c0c7c49b7d845e79d27ebf42073667b' AND action IN ('SAL','QRS','RFD');
SELECT 'verse', SUM(amount)/100.0 FROM fedow_core_transaction
  WHERE sender_id='<WALLET>' AND asset_id='4c0c7c49b7d845e79d27ebf42073667b' AND action='BNK';
SELECT 'token', value/100.0 FROM fedow_core_token
  WHERE wallet_id='<WALLET>' AND asset_id='4c0c7c49b7d845e79d27ebf42073667b';
```

### 10.5 Confirmation côté LaBoutik (instance du lieu)

```python
from APIcashless.models import ArticleVendu, MoyenPaiement, Articles
from django.db.models import Sum, F
sf = ArticleVendu.objects.filter(moyen_paiement__categorie=MoyenPaiement.STRIPE_FED).exclude(article__methode_choices=Articles.FRACTIONNE)
vers = ArticleVendu.objects.filter(article__name="Stripe TiBillet transfert")
enc = sf.aggregate(t=Sum(F('qty')*F('prix')))['t'] or 0
rev = vers.aggregate(t=Sum(F('qty')*F('prix')))['t'] or 0
print("Encaissé SF:", enc, "| Versé:", rev, "| Reste dû:", round(float(enc)-float(rev), 2))
```

---

## 11. Fichiers concernés

| Fichier | Rôle |
|---|---|
| `fedow_core/models.py` → `Transaction.save()` | cause racine + patch token (`F()` delta) |
| `fedow_core/models.py` → `_previous_asset_transaction()` | source des forks de chaîne de hash |
| `fedow_core/signals.py` → `transaction_webhook_new_membership` | webhook synchrone (raison du « sans `@atomic` ») |
| `fedow_core/management/commands/global_asset_bank_stripe_deposit.py` | création manuelle de `DEPOSIT` |
| (à créer) `fedow_core/management/commands/reconcile_tokens.py` | réconciliation des soldes |
| LaBoutik `webview/views.py` → `methode_VC` | remboursement non vérifié (point annexe) |
| LaBoutik `administration/ticketZ_V4.py` | rapports (source fiable du flux) |
