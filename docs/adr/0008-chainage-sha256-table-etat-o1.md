# ADR-0008 : Chaînage cryptographique SHA-256 via table d'état en O(1)

* **Statut** : Accepté (Implémenté en V1)
* **Date** : 2026-11-16

## Contexte
Pour prouver l'infalsifiabilité du registre d'audit, chaque événement doit intégrer l'empreinte cryptographique de l'événement précédent dans une chaîne ininterrompue :
$$\text{event\_hash}_n = \text{SHA-256}(\text{prev\_hash}_{n-1} : \text{seq}_n : \text{canonical\_json})$$

Cependant, deux problèmes majeurs se posent :
1. **Performance** : Calculer l'empreinte précédente en faisant `SELECT last_seq, last_hash FROM audit_events ORDER BY integrity_seq DESC LIMIT 1` deviendrait de plus en plus lent à mesure que la table grandit ($O(\log N)$ ou $O(N)$).
2. **Moindres Privilèges** : Le rôle d'ingestion `deedbook_ingest` ne doit posséder aucun droit de lecture (`SELECT`) sur la table `audit_events`.
3. **Concurrence** : Deux requêtes d'ingestion simultanées ne doivent jamais générer la même séquence ou créer un trou dans la numérotation.

## Décision
Introduire une table dédiée `deedbook.chain_state` (contenant une seule ligne `id = 1`, `last_seq`, `last_hash`, `updated_at`).
Lors de l'ingestion d'un lot :
1. Ouvrir une transaction PostgreSQL.
2. Poser un verrou ligne exclusif : `SELECT last_seq, last_hash FROM deedbook.chain_state WHERE id = 1 FOR UPDATE`.
3. Calculer séquentiellement en mémoire les empreintes SHA-256 des événements du lot.
4. Mettre à jour `chain_state` avec les nouvelles valeurs de fin de lot.
5. Accorder au rôle `deedbook_ingest` les droits `SELECT, UPDATE, INSERT` sur `chain_state`, tout en maintenant son interdiction absolue de `SELECT` sur `audit_events`.

## Conséquences
### Positives
* **Complexité en temps constant $O(1)$** : L'acquisition du dernier hash et de la dernière séquence est instantanée, quel que soit le nombre de millions d'événements déjà stockés.
* **Sérialisation stricte sans condition de course** : Le verrou `FOR UPDATE` empêche tout fork ou séquence en doublon entre workers concurrents.
* **Respect du moindre privilège** : `deedbook_ingest` n'a toujours aucun accès en lecture à l'historique d'audit `audit_events`.

### Négatives / Contraintes
* L'ingestion devient strictement sérialisée au niveau de la base (goulot d'étranglement intentionnel pour garantir l'ordre strict de la chaîne de blocs/événements).

## Alternatives écartées
* **`SELECT MAX(integrity_seq)` sur `audit_events`** : Rejeté pour dégradation des performances et violation du principe du moindre privilège.
* **Séquence PostgreSQL (`CREATE SEQUENCE`) seule** : Rejetée car une séquence génère des trous en cas de rollback de transaction et ne stocke pas le hash précédent.
