# Image PostgreSQL 16 avec pgAudit préinstallé
# pgAudit journalise les opérations côté base (accès directs, M6/V1)
# Le dépôt PGDG est déjà configuré dans l'image officielle postgres
FROM postgres:16

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgaudit \
    && rm -rf /var/lib/apt/lists/*

# Chargé au démarrage ; l'audit proprement dite se configure par base
# (pgaudit.log / pgaudit.role) lors de l'initialisation
CMD ["postgres", "-c", "shared_preload_libraries=pgaudit"]
