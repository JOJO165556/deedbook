# ADR-0002 : FastAPI et Python pour l'API du moteur

* **Statut** : Accepté
* **Date** : 2026-11-08

## Contexte
Le moteur `deedbook` expose une interface HTTP REST pour recevoir les événements d'audit et permettre leur consultation/recherche. Il nécessite un framework performant, asynchrone, validant rigoureusement les types et formats de données en entrée.

## Décision
Adopter **Python 3.13+ et FastAPI** (adossé à Pydantic v2 et Starlette / Uvicorn).

## Conséquences
### Positives
* Validation formelle stricte des schémas d'ingestion (via Pydantic v2 en C/Rust) avec interdiction stricte des champs inconnus (`extra="forbid"`).
* Génération automatique et contractuelle de la spécification OpenAPI / Swagger (`/docs`).
* Performances asynchrones I/O-bound (`asyncio`) adaptées aux flux d'ingestion concurrents.
* Écosystème cryptographique et PostgreSQL mature (`cryptography`, `psycopg` 3).

### Négatives / Contraintes
* Consommation mémoire supérieure à un binaire compilé en Go ou Rust.

## Alternatives écartées
* **Go (Gin/Chi)** : Performances brutes supérieures mais développement plus verbeux pour la validation de schémas JSON complexes et polymorphiques.
* **Rust (Actix/Axum)** : Coût de développement et complexité de maintenance trop élevés pour la portée du projet.
* **Flask / Django** : Frameworks synchrones par défaut, génération OpenAPI non native sans librairies tierces lourdes.
