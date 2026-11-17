# ADR-0007 : Stratégie de partitionnement et politique de rétention

* **Statut** : Proposé (prévu jalon M8 / V1-V2)
* **Date** : 2026-11-08 (Actualisé : 2026-11-17)

## Contexte
Les tables d'audit accumulent des volumes de données croissants. Une politique de rétention (`[retention] default_days = 365` dans `deedbook.toml`) doit permettre de purger ou d'archiver les événements expirés sans compromettre la vérification de l'intégrité séquentielle (`deedbook verify`).
Sous PostgreSQL, le partitionnement natif (`PARTITION BY RANGE (received_at)`) impose que la clé primaire de la table contienne la colonne de partitionnement, ce qui empêche d'avoir une contrainte d'unicité directe sur `event_id` seul.

## Décision
1. Conserver `audit_events` comme une **table simple** non partitionnée pour les phases V0 et V1, afin de garantir l'unicité stricte sur `event_id` et la déduplication instantanée des rejeux.
2. Définir pour le jalon M8 (rétention) un mécanisme d'**archivage scellé par période** :
   - Clôture et exportation d'un bloc de période révolue dans une archive signée.
   - Enregistrement d'un point de reprise (*checkpoint hash*) dans la base.
   - Purge contrôlée des événements archivés via une procédure administrative sécurisée contournant le trigger d'immutabilité de manière auditable.

## Conséquences
### Positives
* Simplicité maximale du schéma en V0/V1 sans complexité de tables partitionnées.
* Déduplication en temps constant sur `event_id` et `idempotency_key`.
* Auditabilité préservée post-purge grâce aux checkpoints d'archivage.

### Négatives / Contraintes
* La purge future nécessite un mécanisme de checkpoint explicite pour que `deedbook verify` puisse vérifier la chaîne à partir d'une date donnée sans exiger l'intégralité du passé.

## Alternatives écartées
* **Partitionnement natif immédiat en V0** : Rejeté car obligerait à inclure `received_at` dans la clé primaire, affaiblissant la détection immédiate des doublons par `event_id`.
