# ADR-0004 : Moteur indépendant hors processus de l'application auditée

* **Statut** : Accepté
* **Date** : 2026-11-08

## Contexte
Une tentation fréquente en audit consiste à embarquer le journal directement dans la base de données métier de l'application hôte ou dans le même processus applicatif (ex: table `audit_log` dans l'application principale). Si l'application hôte est compromise, l'attaquant contrôle alors directement la table d'audit et peut en altérer le contenu sans barrière étanche.

## Décision
Concevoir `deedbook` comme un **service autonome, indépendant et isolé** :
1. Une base de données PostgreSQL distincte de l'application hôte.
2. Un processus API serveur distinct.
3. Une communication réseau sécurisée par jeton applicatif.

## Conséquences
### Positives
* Valeur probante préservée : même si l'application hôte est totalement compromise, elle ne possède que les droits d'un émetteur avec un jeton d'ingestion (rôle PostgreSQL `deedbook_ingest` INSERT-seul, aucun SELECT/UPDATE/DELETE).
* Découplage du cycle de vie des données d'audit de celui des données métier.

### Négatives / Contraintes
* Nécessite le déploiement d'un service et d'une instance de base dédiés.
* Latence réseau légère lors de l'envoi des lots (compensée par le worker d'arrière-plan du SDK).

## Alternatives écartées
* **Mode bibliothèque / Embedded SQLite** : Rejeté car perd toute valeur probante et toute protection contre un attaquant ayant compromis l'hôte.
* **Tables d'audit dans la base applicative métier** : Rejeté pour éviter la confusion des privilèges administrateur (le DBA de l'application ne doit pas pouvoir effacer ses traces d'audit).
