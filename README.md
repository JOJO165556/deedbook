# deedbook

Moteur d'audit et de gouvernance pour bases de données **PostgreSQL**, usage personnel.

## État

- **V0 (Noyau)** : Implémenté et validé.
  - Ingestion d'événements et de lots atomiques (`POST /v1/events`).
  - Validation Pydantic stricte (schéma v1.0, typage, immutabilité).
  - Masquage des champs sensibles (redact, hash HMAC-SHA256 salé, mask).
  - Contrôle d'accès et authentification par jetons applicatifs et admin.
  - Rôles PostgreSQL à moindres privilèges (`deedbook_ingest` INSERT-seul, `deedbook_read` SELECT-seul).
  - Consultation unitaire (`GET /v1/events/{id}`) et recherche multi-critères avec pagination (`GET /v1/events`).
  - SDK Python (`deedbook-sdk`) garantissant le zéro plantage de l'application hôte.
- **Feuille de route** : V0 noyau (achevé) → V1 preuve & intégrité cryptographique → V2 administration → V3 gouvernance.

## Structure

| Chemin | Rôle |
|---|---|
| `server/` | Moteur FastAPI (`deedbook`) — ingestion, recherche, masquage, CLI |
| `sdk-python/` | Kit d'intégration client Python (`deedbook-sdk`) — zéro plantage hôte |
| `deploy/` | `docker-compose.yml`, conteneur Postgres + pgAudit |
| `docs/` | Spécification formelle v1.0, modèle de menace et décisions d'architecture (ADR) |
| `deedbook.toml` | Politique du projet (sans secret) |
| `.env.example` | Modèle de variables d'environnement (le vrai `.env` reste strictement hors Git) |

## Démarrage rapide

```bash
# 1. Configuration des secrets
cp .env.example .env

# 2. Démarrage de la base PostgreSQL
docker compose -f deploy/docker-compose.yml --env-file .env up -d db

# 3. Installation et vérification de l'environnement
cd server && uv sync
uv run deedbook init     # applique les migrations et configure les rôles
uv run deedbook doctor   # vérifie la configuration, les droits réels et l'horloge

# 4. Enregistrement d'une application
uv run deedbook project add monapp

# 5. Démarrage du serveur API
uv run deedbook serve --port 8000
```

## Documentation

- [Spécification de l'événement d'audit v1.0](docs/specification-evenement-audit.md) : format JSON, validation, règles d'action et masquage.
- [Modèle de menace](docs/modele-de-menace.md) : scénarios S1 à S6 et plan de tests d'attaque.
- [Journal des décisions d'architecture (ADR)](docs/adr/README.md) : décisions structurantes D001 à D007.

## Règles fondamentales

- **Secrets exclusivement en variables d'environnement** (`.env`), politique sans secret dans `deedbook.toml`.
- **Rôles à moindres privilèges** : le rôle d'ingestion ne possède aucun droit de modification ou de lecture des tables d'audit.
- **Contrat zéro plantage hôte** : le SDK Python intercepte toute exception sans jamais faire échouer l'application hôte.
- **Immuabilité** : triggers de base interdisant `UPDATE`, `DELETE` et `TRUNCATE` sur les tables d'audit. Les migrations appliquées ne sont jamais modifiées.
- **Hook anti-secrets actif** : `git config core.hooksPath .githooks`.
