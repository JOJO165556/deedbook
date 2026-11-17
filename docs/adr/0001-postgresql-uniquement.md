# ADR-0001 : PostgreSQL uniquement comme moteur de base de données

* **Statut** : Accepté
* **Date** : 2026-11-08

## Contexte
Le moteur d'audit `deedbook` a besoin d'un stockage transactionnel robuste, garantissant l'atomicité, la consistance et des mécanismes d'isolation stricts. Multiplier les bases de données supportées (MySQL, SQLite, SQL Server, Oracle) augmente la surface de maintenance, complexifie les migrations et empêche d'exploiter les fonctionnalités avancées propres à PostgreSQL.

## Décision
Utiliser **exclusivement PostgreSQL** (version 16+) comme moteur de base de données du registre d'audit.

## Conséquences
### Positives
* Utilisation native des fonctionnalités avancées : triggers en PL/pgSQL pour l'immutabilité, types JSONB avec indexation GIN, vérification fine des droits par rôles (`has_table_privilege`).
* Verrouillage précis au niveau de la ligne (`SELECT ... FOR UPDATE`) pour le chaînage d'intégrité.
* Un seul système de base de données à exploiter et monitorer.

### Négatives / Contraintes
* L'application nécessite obligatoirement une instance PostgreSQL accessible. Pas de support pour des bases légères de type SQLite sans serveur.

## Alternatives écartées
* **SQLite** : Écarté car mono-écrivain, manque de gestion fine des rôles et des triggers d'isolation transactionnelle avancés.
* **MySQL / MariaDB** : Écarté pour éviter le coût d'abstraction SQL multi-moteur sans valeur ajoutée.
* **Oracle / SQL Server** : Écartés pour des raisons de complexité d'exploitation et de coûts de licence pour un usage personnel/interne.
