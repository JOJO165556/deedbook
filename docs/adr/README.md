# Journal des décisions d'architecture (ADR)

Une page par décision structurante, avec les options écartées.
Format : contexte → décision → conséquences → alternatives écartées.

## Décisions actées (issues de la charte)

- **D001 — PostgreSQL uniquement** : un seul système à exploquer. MySQL/SQL
  Server/Oracle écartés jusqu'à preuve du besoin (V3+).
- **D002 — FastAPI + Python** : documentation OpenAPI automatique de
  l'interface, technologie maîtrisée.
- **D003 — Pas de tableau de bord au départ** : CLI + OpenAPI suffisent en V0 ;
  Next.js/TypeScript arrive en V1–V2. Évite de construire l'écran avant le cœur.
- **D004 — Mode embarqué écarté** : le journal dans le même processus/base que
  l'application perd son indépendance et sa valeur probante.
- **D005 — Kafka, OpenSearch, Kubernetes écartés** : complexité
  d'exploitation disproportionnée pour un usage personnel.
- **D006 — Celery/Redis non retenus** : planificateur simple d'abord ; on
  n'ajoute un composant que si le besoin est démontré.

## À décider

- (aucune pour l'instant)
