# Modèle de menace — deedbook

Squelette dérivé de la charte (§5.2). Document à compléter avant V0 :
scénarios, hypothèses, tests d'attaque.

## Hypothèses

- L'hébergement du moteur et ses clés ne sont pas entièrement compromis
  (limite assumée : qui contrôle serveur + clés peut reconstruire la chaîne).
- Pas de déni de service massif, pas de compromission du poste du propriétaire.

## Scénarios et parades

| # | Scénario | Parade | Statut |
|---|----------|--------|--------|
| S1 | Application compromise tente d'effacer ses traces | Compte d'ingestion en ajout seul, sans droit de suppression | À implémenter (init) |
| S2 | Accès direct à la base hors application | Écritures orphelines + alerte (pgAudit) | V1 |
| S3 | Erreur d'administration (mauvais droit) | Liste fermée d'opérations, aperçu, confirmation, journalisation | V2 |
| S4 | Fuite de clés ou secrets | Stockage séparé, droits minimaux, rotation | Partiel (socle) |
| S5 | Altération du journal dans le moteur | Chaînage, signature, vérification planifiée | V1 |
| S6 | Contenu malveillant dans un champ journalisé | Validation à l'entrée, échappement à l'affichage | À faire (ingestion) |

## Tests d'attaque

Plan à rédiger (charte §10) : un test par scénario, résultats attendus
consignés ici.
