# Modèle de menace - deedbook

Version 1.0 - couvre les scénarios S1 à S6
Statut : rédaction pour V0. Les tests d'attaque (§ plan de tests) arrivent en V1.

## 1. Périmètre et hypothèses

Le moteur d'audit deedbook comprend : l'API FastAPI, la base PostgreSQL
dédiée, le SDK d'intégration, le CLI d'administration.

Hypothèses retenues (hors modèle) :

- Un attaquant ne contrôle pas simultanément l'hébergement du moteur et ses
  clés de signature. Cette limite est levée partiellement par l'ancrage
  externe des empreintes (V1+).
- Pas de déni de service massif : la disponibilité prime, un flood peut
  retarder des événements sans les détruire.
- Le poste du propriétaire n'est pas compromis.
- Les applications auditées sont du code de confiance relatif : une
  application compromise est un scénario couvert (S1), pas une hypothèse.

Actifs à protéger, par ordre :

1. L'intégrité du journal (preuve qu'aucune ligne n'a été altérée)
2. La confidentialité des événements (données sensibles masquées)
3. Le pouvoir d'administration (rôles, droits, jetons)
4. La disponibilité du pipeline d'ingestion

## 2. Acteurs de menace

| Acteur | Capacités |
|---|---|
| Application compromise | Jeton d'ingestion valide, peut émettre des événements forgés |
| Utilisateur interne curieux | Accès read à la base ou à l'API de lecture |
| Administrateur distrait ou forcé | Accès admin complet au moteur |
| Attaquant externe | Aucun accès initial ; tente injection via champs journalisés |
| Opérateur hostile (futur) | Contrôle hébergement + clés - hors modèle actuel |

## 3. Scénarios et parades

### S1 - Application compromise tente d'effacer ses traces

Scénario : l'application auditée est piratée ; l'attaquant veut supprimer ou
modifier les événements qui la compromettent.

Parades en place :

- Rôle `deedbook_ingest` : INSERT seul, aucun UPDATE/DELETE/SELECT
  (vérifié par `doctor` et testé)
- Triggers `reject_mutation` sur `audit_events` et `audit_batches` :
  UPDATE, DELETE et TRUNCATE levés même pour le superuser
- Journal des lots `audit_batches` : un lot partiellement rejoué laisse une
  trace

Limite : un attaquant avec l'URL admin (`DEEDBOOK_DATABASE_URL`) peut
théoriquement désactiver les triggers. Parade complémentaire : les secrets
admin ne quittent jamais le `.env` du moteur, jamais distribués aux apps.

### S2 - Accès direct à la base hors application (écriture orpheline)

Scénario : quelqu'un modifie la base PostgreSQL auditable directement,
sans passer par l'application ni par le moteur.

Parades :

- pgAudit sur la base cible (image `deploy/db`) journalise les opérations
  côté base
- Rapprochement journal base / journal applicatif par `correlation_id` :
  une écriture sans événement applicatif correspondant = orpheline
- Alerte (M6, V1)

Statut : collecte pgAudit disponible, détection à implémenter en V1.

### S3 - Erreur d'administration (mauvais droit accordé)

Scénario : l'opérateur accorde par mégarde des droits trop larges.

Parades :

- `init` crée des rôles à droits minimaux ; `doctor` revérifie les droits
  réels (`has_table_privilege`), pas seulement les intentions
- `deedbook project add` : liste fermée implicite (un seul type d'opération
  pour l'instant), jeton généré, hash seul stocké
- Toute opération d'administration future passe par une liste fermée
  d'opérations avec aperçu et confirmation (M11, V2)
- Les changements de droits sont eux-mêmes des événements audités

### S4 - Fuite de clés ou de secrets

Scénario : `.env`, clé de signature ou jeton admin compromis.

Parades en place :

- Secrets uniquement en variables d'environnement ; `.env` hors Git
  (`.gitignore` + hook pre-commit avec détection de motifs)
- `deedbook.toml` ne contient aucune valeur secrète
- Clés affichées une seule fois à la génération (`init`, `project add`)
- Mots de passe des rôles DB aléatoires, non réaffichés ensuite
- Champs `SecretStr` dans la configuration : jamais affichés en log

Parades à venir : rotation régulière (politique de gestion des clés,
avant V1), droits minimaux déjà en place.

### S5 - Altération du journal à l'intérieur du moteur

Scénario : quelqu'un modifie une ligne d'audit directement en base.

Parades :

- Triggers d'immutabilité (UPDATE/DELETE/TRUNCATE bloqués, même admin)
- Chaînage cryptographique SHA-256 + signature des lots : prévu V1, champs
  `integrity_seq`, `event_hash`, `prev_hash` déjà dans le schéma
- `deedbook verify` : commande de vérification, stub en place
- Ancrage externe des empreintes : évolution post-V3

Limite assumée : qui contrôle serveur + clés peut reconstruire une chaîne
cohérente. Limite assumée et documentée.

### S6 - Contenu malveillant glissé dans un champ journalisé

Scénario : une chaîne contenant du script, du SQL ou du HTML est envoyée
dans un événement pour attaquer le moteur ou le futur tableau de bord.

Parades :

- Validation stricte du format (spec §1) : types, tailles, énumérations
  fermées, rejet du lot entier sur erreur
- Tailles bornées : 100 événements / 256 Ko par lot, `result.message`
  tronqué à 500 caractères
- `change_before`/`change_after` : profondeur 4, 8 Ko max par côté
- Masquage des champs sensibles avant stockage et à l'affichage (M3)
- Échappement à l'affichage : exigence pour le tableau de bord (V1),
  tout rendu HTML devra échapper par défaut

## 4. Matrice des parades

| Parade | S1 | S2 | S3 | S4 | S5 | S6 |
|---|---|---|---|---|---|---|
| Rôles à droits minimaux | x | | x | x | | |
| Triggers immuabilité | x | | | | x | |
| Masquage à la source | | | | x | | x |
| Validation stricte | | | | | | x |
| Hook anti-secrets | | | | x | | |
| pgAudit + corrélation | | x | | | | |
| Chaînage + signature (V1) | | | | | x | |
| Liste fermée d'opérations (V2) | | | x | | | |

## 5. Plan de tests d'attaque (V1)

Un test par scénario, exécutable et reproductible :

| Test | Scénario | Procédure | Résultat attendu |
|---|---|---|---|
| ATK-01 | S1 | Se connecter avec `DEEDBOOK_INGEST_URL`, tenter UPDATE/DELETE/TRUNCATE | Permission denied / trigger reject |
| ATK-02 | S1 | Se connecter avec `DEEDBOOK_DATABASE_URL` (admin), tenter UPDATE | Trigger reject_violation |
| ATK-03 | S5 | UPDATE manuel d'une ligne `audit_events` | Trigger reject_violation |
| ATK-04 | S5 | Modifier `event_hash` puis `deedbook verify` | Incohérence détectée (V1) |
| ATK-05 | S2 | Écriture directe en base cible hors application | Alerte orpheline (V1) |
| ATK-06 | S6 | Envoyer un événement avec `<script>` dans `result.message` | Accepté mais inerte ; affichage échappé |
| ATK-07 | S6 | Envoyer un lot de 101 événements | 413 batch_too_large |
| ATK-08 | S4 | `git add .env` puis commit | Hook pre-commit refuse |
| ATK-09 | S3 | `project add` avec nom invalide | Rejet validation |
| ATK-10 | S1 | Rejouer un lot avec les mêmes `event_id` | Déduplication, aucun doublon |

## 6. Revue

À revoir avant V1 : ajout des scénarios liés au chaînage (rejeu de lots,
troncature de fin de chaîne), à la conservation (purge contrôlée) et aux
modules activables (un module inactif ne doit exposer aucune route).
