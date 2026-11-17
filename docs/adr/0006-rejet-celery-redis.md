# ADR-0006 : Rejet de Celery et Redis pour la file d'attente d'ingestion

* **Statut** : Accepté
* **Date** : 2026-11-08

## Contexte
Pour éviter de ralentir l'application hôte lors de l'enregistrement d'événements d'audit, une file d'attente asynchrone est requise. L'approche traditionnelle Python utilise un broker Redis couplé à des workers Celery.

## Décision
Rejeter l'ajout de Redis et Celery. Implémenter l'asynchronisme côté client au sein du SDK Python (`deedbook-sdk`) via un **tampon mémoire borné (`queue.Queue`)** et un **thread travailleur d'arrière-plan**.

## Conséquences
### Positives
* Zéro dépendance d'infrastructure additionnelle pour les applications clientes (pas d'instance Redis à déployer et surveiller).
* Garantie stricte "zéro plantage hôte" : le thread SDK gère les retries et abandonne les événements si la file de 10 000 messages est saturée, empêchant tout crash de l'hôte.
* Débit optimisé par groupement en lots (*batching*) de 100 événements ou 2 secondes.

### Négatives / Contraintes
* Si l'application hôte est tuée brutalement (`kill -9` ou coupure de courant), les événements encore dans la file mémoire avant émission peuvent être perdus. Ce compromis disponibilité/performance est assumé.

## Alternatives écartées
* **Celery + Redis** : Ajoute deux composants lourds à maintenir pour un besoin de simple buffer asynchrone.
* **Émission synchrone bloquante HTTP** : Rejetée car violerait le contrat "zéro impact de latence" sur l'application hôte.
