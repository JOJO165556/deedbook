# ADR-0003 : Interface CLI et OpenAPI sans tableau de bord graphique au départ

* **Statut** : Accepté
* **Date** : 2026-11-08

## Contexte
Un moteur d'audit requiert des outils d'exploitation pour l'administration (initialisation, ajout de projets, diagnostics de santé, vérification d'intégrité). Construire une interface web graphique (Dashboard React/Next.js) dès le départ disperserait les efforts de conception avant que le cœur cryptographique et sécuritaire ne soit stable.

## Décision
Limiter les interfaces d'exploitation en V0/V1 à la **ligne de commande CLI (`deedbook`)** et à la documentation interactive **OpenAPI / Swagger**. Le tableau de bord visuel est différé en V2+.

## Conséquences
### Positives
* Focalisation exclusive sur le cœur : sécurité, validation formelle, immutabilité et preuves d'intégrité.
* Administration scriptable en ligne de commande et automatisable en intégration continue (`deedbook doctor`, `deedbook verify`).
* Surface d'attaque réduite (pas de dépendances frontend, pas de failles web XSS/CSRF sur l'interface d'administration).

### Négatives / Contraintes
* Ergonomie moins accessible pour les utilisateurs non habitués au terminal.

## Alternatives écartées
* **Dashboard Next.js / TypeScript dès la V0** : Rejeté pour éviter de concevoir l'écran avant que les modèles de données et de menace ne soient stabilisés.
* **Interface admin Django générique** : Rejetée car incompatible avec le choix de FastAPI et imposant un couplage fort avec l'ORM Django.
