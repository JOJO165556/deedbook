# ADR-0010 : Système de modules activables et isolation des extensions

* **Statut** : Accepté (Implémenté en V1)
* **Date** : 2026-11-18

## Contexte
Le moteur deedbook doit pouvoir accueillir des fonctionnalités optionnelles (alertes webhooks, export SIEM, notifications critiques, connecteurs tiers) sans alourdir le noyau d'ingestion ni exposer des endpoints d'API inutilisés qui augmenteraient la surface d'attaque.

## Décision
Adopter une architecture modulaire basée sur la politique déclarative `deedbook.toml` :
1. Chaque module réside dans son propre sous-dossier de `deedbook.modules` avec un manifeste `module.toml`.
2. Un module n'est chargé et ses routes d'API ne sont exposées que s'il figure explicitement dans la liste `[modules] enabled` de `deedbook.toml`.
3. Par défaut (`enabled = []`), aucun module n'est actif, aucune route d'extension n'est enregistrée dans FastAPI (retour 404).
4. Le module de référence `webhooks` permet d'émettre des alertes HTTP signées Ed25519 lors d'événements critiques (`result_status = "denied"`, modifications d'autorisations) sans bloquer le pipeline d'ingestion.

## Conséquences
### Positives
* **Surface d'attaque minimale** : Les routes de modules non activés sont totalement absentes du schéma OpenAPI et inaccessibles.
* **Extensibilité modulaire** : Les nouvelles capacités s'ajoutent de manière isolée sans impacter les tables ou le code du noyau.
* **Résilience** : L'échec d'un appel externe de module (ex. indisponibilité d'un récepteur de webhook) est silencieux et ne bloque jamais l'ingestion cryptographique.

### Négatives / Contraintes
* Tout nouveau module doit déclarer un manifeste `module.toml` conforme et respecter le cycle de chargement dynamique.

## Alternatives écartées
* **Architecture monolithique tout-activé** : Exposer toutes les routes en permanence avec des drapeaux d'activation conditionnels en base : rejeté pour éviter d'exposer des points d'entrée inutiles.
* **Microservices externes via message broker (Kafka, RabbitMQ)** : Rejeté pour respecter le principe d'architecture sans dépendance lourde externe (cf. ADR-0005).
