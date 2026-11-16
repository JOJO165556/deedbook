-- Migration 0002 : État du chaînage cryptographique V1
-- Permet à deedbook_ingest d'enchaîner les empreintes en O(1) sous verrou ligne (FOR UPDATE)
-- sans avoir besoin de SELECT sur audit_events (préservation de l'INSERT-seul).

CREATE TABLE IF NOT EXISTS deedbook.chain_state (
    id         integer PRIMARY KEY CHECK (id = 1),
    last_seq   bigint NOT NULL DEFAULT 0,
    last_hash  text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Initialisation avec l'empreinte genesis sentinelle
INSERT INTO deedbook.chain_state (id, last_seq, last_hash)
VALUES (1, 0, '0000000000000000000000000000000000000000000000000000000000000000')
ON CONFLICT (id) DO NOTHING;

-- Synchronisation si des événements existent déjà
DO $$
DECLARE
    r RECORD;
BEGIN
    SELECT integrity_seq, event_hash INTO r
    FROM deedbook.audit_events
    WHERE integrity_seq IS NOT NULL
    ORDER BY integrity_seq DESC
    LIMIT 1;

    IF r.integrity_seq IS NOT NULL THEN
        UPDATE deedbook.chain_state
        SET last_seq = r.integrity_seq, last_hash = r.event_hash, updated_at = now()
        WHERE id = 1;
    END IF;
END $$;
