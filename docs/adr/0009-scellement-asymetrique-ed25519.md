# ADR-0009 : Scellement asymétrique des lots par signatures Ed25519

* **Statut** : Accepté (Implémenté en V1)
* **Date** : 2026-11-16

## Contexte
Le chaînage SHA-256 garantit l'intégrité séquentielle des événements, mais n'authentifie pas de façon asymétrique l'émetteur ou l'instance ayant produit le lot. Si un attaquant modifie un bloc et réécrit l'historique sans clé asymétrique, un simple HMAC partagé ne permettrait pas à un auditeur tiers externe de vérifier l'authenticité sans posséder le secret de signature.

## Décision
Signer chaque lot d'ingestion enregistré dans `deedbook.audit_batches` avec une **clé asymétrique Ed25519** (courbe Edwards 25519, 64 octets).
Le payload signé contient canoniquement :
```text
deedbook:batch:v1:<batch_id>:<app>:<schema_version>:<event_count>:<first_seq>:<last_seq>:<first_hash>:<last_hash>
```

## Conséquences
### Positives
* **Non-répudiation et authenticité** : La signature prouve que le lot a été forgé et scellé par l'instance légitime détenant la clé privée Ed25519.
* **Vérifiabilité par des tiers** : N'importe quel auditeur externe peut vérifier la signature de tous les lots à l'aide de la clé publique seule, sans jamais avoir accès aux secrets d'écriture du moteur.
* **Performances cryptographiques** : Ed25519 offre des signatures ultra-rapides et compactes (64 octets), avec une résistance native aux attaques par canaux auxiliaires (*side-channel attacks*).

### Négatives / Contraintes
* Nécessite la génération et la gestion sécurisée de la clé privée `DEEDBOOK_SIGNING_KEY` dans l'environnement (`.env`).

## Alternatives écartées
* **RSA (2048 / 4096 bits)** : Signatures plus lentes, empreinte volumique plus lourde, sensibilité accrue aux attaques temporelles.
* **HMAC-SHA256 seul** : Cryptographie symétrique ne permettant pas la vérification publique sans divulguer la clé secrète de signature.
* **ECDSA (secp256k1 / NIST P-256)** : Rejeté au profit d'Ed25519 pour sa simplicité d'implémentation et l'absence de biais sur le générateur de nombres aléatoires (*k-nonce*).
