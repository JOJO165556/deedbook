# deedbook

Moteur d'audit et de gouvernance pour bases de données **PostgreSQL**, usage personnel.

## État

Socle en cours de construction - aucune fonctionnalité du moteur n'est implémentée.
Feuille de route : V0 noyau → V1 preuve/supervision → V2 administration → V3 gouvernance.

## Structure

| Chemin | Rôle |
|---|---|
| `server/` | Moteur FastAPI (`deedbook`) - ingestion, recherche, chaînage, CLI |
| `sdk-python/` | Kit d'intégration Python (`deedbook-sdk`) - zéro plantage hôte |
| `deploy/` | `docker-compose.yml`, image Postgres + pgAudit |
| `docs/` | Cadrage, modèle de menace, ADR, décisions |
| `deedbook.toml` | Politique du projet (sans secret) |
| `.env.example` | Modèle de secrets (le vrai `.env` reste hors Git) |

## Setup

```bash
cp .env.example .env
docker compose -f deploy/docker-compose.yml --env-file .env up -d db
cd server && uv sync
uv run deedbook doctor   # refuse de démarrer tant que .env est incomplet
```

## Règles

- Secrets uniquement en variables d'environnement ; politique dans `deedbook.toml`.
- Le serveur refuse de démarrer si une configuration manque ; le SDK se désactive sans jamais faire tomber l'application hôte.
- Migrations SQL numérotées, jamais modifiées après coup.
- Hook anti-secrets actif : `git config core.hooksPath .githooks` (déjà configuré sur ce clone).
