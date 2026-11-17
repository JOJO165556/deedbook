-- Migration 0003 : Table de suivi des archivages scellés
-- Chaque archivage réussi enregistre un checkpoint qui conditionne la purge.

CREATE TABLE IF NOT EXISTS deedbook.archive_checkpoints (
    id              serial PRIMARY KEY,
    archived_before date        NOT NULL,
    event_count     integer     NOT NULL CHECK (event_count > 0),
    last_seq        bigint      NOT NULL,
    last_hash       text        NOT NULL,
    archive_path    text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS archive_checkpoints_before_idx
    ON deedbook.archive_checkpoints (archived_before);
