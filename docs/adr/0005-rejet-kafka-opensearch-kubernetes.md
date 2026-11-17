# ADR-0005 : Rejet de Kafka, OpenSearch et Kubernetes

* **Statut** : Accepté
* **Date** : 2026-11-08

## Contexte
Les architectures d'entreprise pour le logging et l'audit s'appuient fréquemment sur des clusters de bus de messages (Kafka, RabbitMQ), des moteurs d'indexation distribués (OpenSearch, Elasticsearch) et des orchestrateurs complexes (Kubernetes). `deedbook` vise un déploiement pragmatique, robuste et opérable par une seule personne pour un usage interne ou de moyenne échelle.

## Décision
Rejeter explicitement Kafka, OpenSearch et Kubernetes. Reposer exclusivement sur **PostgreSQL standard**, **FastAPI** et **Docker Compose**.

## Conséquences
### Positives
* Exploitation simple : une commande `docker compose up -d` suffit.
* Empreinte mémoire minimale (moins de 250 Mo de RAM au repos contre plusieurs gigaoctets pour la suite ELK/Kafka).
* Sauvegardes et restaurations triviales via les outils natifs PostgreSQL (`pg_dump`, `pg_basebackup`).
* Cohérence transactionnelle ACID immédiate impossible à obtenir facilement sur un système distribué multi-composants.

### Négatives / Contraintes
* Moins adapté aux débits massifs de millions d'événements par seconde (hors cible du projet).

## Alternatives écartées
* **Apache Kafka** : Complexité opérationnelle injustifiée pour les volumes visés.
* **OpenSearch / Elasticsearch** : PostgreSQL et les index GIN JSONB répondent parfaitement aux besoins de recherche multi-critères.
* **Kubernetes (K8s)** : Déploiement surdimensionné pour une infrastructure autonome.
