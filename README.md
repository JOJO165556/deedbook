# deedbook

Moteur d'audit PostgreSQL à détection d'altération : toute modification ou suppression d'un événement devient détectable. Il enregistre qui a fait quoi, relie l'action applicative à l'opération en base et signale les écritures directes. Il n'empêche pas une falsification par quelqu'un qui contrôle à la fois le serveur du moteur et ses clés : il la rend détectable.

> [!WARNING]
> Expérimental, non audité. Ne l'utilise pas comme seule preuve en justice.

[![CI](https://github.com/JOJO165556/deedbook/actions/workflows/ci.yml/badge.svg)](https://github.com/JOJO165556/deedbook/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/docker-ghcr.io-blue?logo=docker&logoColor=white)](https://github.com/JOJO165556/deedbook/pkgs/container/deedbook)
[![Python](https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-16-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Security Policy](https://img.shields.io/badge/security-policy-green.svg)](SECURITY.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Fonctionnalités clés

* **Chaînage cryptographique continu** : chaque événement référence le hash du précédent via une séquence strictement ordonnée en base (condensats SHA-256 continus, détection immédiate de rupture ou d'insertion).
* **Accusés et points de contrôle signés** : chaque lot d'ingestion génère un accusé de réception signé et chaque session d'archivage produit un point de contrôle scellé par signature asymétrique Ed25519.
* **Résilience applicative** : le SDK client (`deedbook-sdk`) isole l'application émettrice via une file mémoire bornée et un travailleur asynchrone non-bloquant en arrière-plan ; aucune indisponibilité du collecteur ne bloque l'application hôte.
* **Rôles PostgreSQL à moindres privilèges** :
  * `deedbook_ingest` : insertion exclusive (`INSERT`), consultation et mutation formellement interdites.
  * `deedbook_read` : consultation exclusive (`SELECT`).
  * Triggers d'immuabilité bloquant tout `UPDATE`, `DELETE` ou `TRUNCATE` pour les rôles applicatifs.
* **Masquage des données personnelles** : hachage HMAC avec clé secrète (non réversible, mais comparable pour les recherches d'audit), masquage partiel ou suppression des champs sensibles selon la politique définie (respect des principes de minimisation et de protection de la vie privée, notamment loi togolaise).
* **Rapprochement pgAudit (ATK-05)** : corrélation périodique entre les écritures directes enregistrées par pgAudit et les événements reçus pour détecter les mutations clandestines en base de données.
* **Purge et archivage scellé** : la commande administrative d'archivage extrait et signe les événements expirés. La suppression en base (`deedbook purge`) est interdite aux rôles applicatifs et requiert l'inscription préalable d'un point de contrôle signé dans le registre `archive_checkpoints` sous un rôle d'administration dédié.
* **Ancrage externe** : publication régulière des condensats de chaîne vers une destination externe hors du contrôle de l'opérateur local (RFC 3161 / HTTP tiers). Un ancrage interne sous le même périmètre de contrôle ne protège d'aucune falsification conjointe.

---

## Outils et technologies

| Composant | Technologie | Rôle |
|---|---|---|
| **Langage** | Python 3.13 | Serveur d'ingestion, CLI d'administration et SDK client |
| **API Web** | FastAPI, Starlette, Uvicorn | Interface d'ingestion HTTP asynchrone et validation Pydantic |
| **Base de données** | PostgreSQL 16 + pgAudit | Stockage relationnel, contraintes strictes et audit système bas niveau |
| **Pilote BDD** | Psycopg 3 (binaire C) | Connecteur natif avec support JSONB et requêtes composées |
| **Cryptographie** | Cryptography (PyCA) | Signatures Ed25519, condensats SHA-256 et HMAC-SHA256 |
| **Packaging** | Docker, uv, hatchling | Multi-stage build, conteneurs multi-architectures (`amd64`/`arm64`) |
| **CI / CD** | GitHub Actions, GHCR | Audit CVE hebdomadaire, scan Gitleaks, build et release automatisée |

---

## Démarrage rapide

### Option A : Déploiement en production (Docker)

```bash
# 1. Cloner le dépôt et entrer dans le dossier
git clone https://github.com/JOJO165556/deedbook.git
cd deedbook

# 2. Configurer les variables d'environnement
cp .env.example .env
# Renseigner DEEDBOOK_SIGNING_KEY et DEEDBOOK_HMAC_KEY (base64 de 32 octets)

# 3. Initialiser la base de données et les rôles
docker compose -f deploy/docker-compose.prod.yml run --rm api deedbook init

# 4. Démarrer la stack de production (image épinglée 1.0.0)
docker compose -f deploy/docker-compose.prod.yml up -d
```

### Option B : Développement local (avec uv)

```bash
# 1. Cloner et installer les dépendances
git clone https://github.com/JOJO165556/deedbook.git
cd deedbook/server
uv sync

# 2. Initialiser la base et vérifier l'environnement
uv run deedbook init
uv run deedbook doctor

# 3. Enregistrer un projet et démarrer l'API
uv run deedbook project add mon-application
uv run deedbook serve --port 8000
```

---

## Intégration dans vos applications (SDK)

Le paquet `deedbook-sdk` s'installe directement depuis le dépôt git ou un dossier local afin de garantir l'intégrité de la source (non publié sur PyPI pour prévenir les attaques par substitution de nom) :

```bash
# Installation directe depuis GitHub
pip install "deedbook-sdk @ git+https://github.com/JOJO165556/deedbook.git#subdirectory=sdk-python"

# Ou installation depuis le sous-répertoire d'un clone local
# pip install ./sdk-python
```

### Intégration automatique par middleware (FastAPI)

```python
from fastapi import FastAPI
from deedbook_sdk import AuditClient, DeedbookASGIMiddleware

audit_client = AuditClient(
    engine_url="http://localhost:8000",
    api_token="dbk_votre_jeton_ici",
    app_name="mon-application",
)

app = FastAPI()
app.add_middleware(DeedbookASGIMiddleware, client=audit_client)
```

### Émission manuelle d'événements métiers

```python
audit_client.emit(
    action="user.role_change",
    actor={"type": "human", "end_user": "admin@domaine.com", "role": "security"},
    resource={"type": "account", "id": "acc_102", "name": "finance"},
    result={"status": "success"},
    change={"before": {"role": "editor"}, "after": {"role": "admin"}},
)
```

---

## Commandes d'administration (CLI)

```bash
# Gestion des projets et jetons
deedbook project add <nom>           # Enregistre un projet et génère son jeton d'ingestion

# Vérification et cryptographie
deedbook verify                     # Valide la continuité SHA-256 et les signatures Ed25519
deedbook anchor                     # Publie l'empreinte de chaîne vers le tiers d'ancrage externe

# Rétention et archivage
deedbook archive --before 2026-01-01 # Extrait et signe les événements expirés
deedbook purge --before 2026-01-01   # Purge en base sous contrôle d'un point de contrôle signé

# Rapprochement de sécurité
deedbook reconcile --log pgaudit.log # Détecte les écritures orphelines directes en base

# Diagnostic système
deedbook doctor                     # Audit de l'horloge, des permissions réelles et de la config
```

---

## Documentation

* [Guide d'architecture technique](docs/architecture.md) : topologie cryptographique, cycle transactionnel et frontières de confiance.
* [Spécification de l'événement v1.0](docs/specification-evenement-audit.md) : format JSON canonique, typage et politiques de masquage.
* [Modèle de menace](docs/modele-de-menace.md) : analyse STRIDE et banc de tests d'attaque ATK-01 à ATK-10.
* [Politique de sécurité](SECURITY.md) : procédure de signalement responsable de vulnérabilité.
* [Décisions d'architecture (ADR)](docs/adr/) : journal des décisions structurantes D001 à D010.
* [Runbook d'exploitation](docs/runbook-exploitation.md) : procédures d'urgence, rotation des clés et reprise après incident.

---

## Licence

Distribué sous [licence MIT](LICENSE). Copyright (c) 2026 JOJO165556.
