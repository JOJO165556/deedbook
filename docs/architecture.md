# Architecture Système de deedbook

Ce document décrit l'architecture technique, les frontières de confiance, le cycle transactionnel d'ingestion et le modèle cryptographique de **deedbook**.

---

## 1. Diagramme de Flux de Données (DFD)

Le DFD représente les quatre éléments canoniques : **entités externes** (rectangles), **processus** (coins arrondis), **magasins de données** (lignes parallèles) et **flux de données** (flèches étiquetées), ainsi que les **frontières de confiance** (pointillés) là où les données franchissent un niveau de privilège différent.

> Les frontières de confiance indiquent où appliquer STRIDE : validation des entrées, authentification des appelants et contrôle des privilèges.

```mermaid
flowchart TD
    %% Entités externes
    APP["Application Hôte\n(Entité externe)"]
    ADMIN["Opérateur / CLI\n(Entité externe)"]
    ANCHOR["Serveur d'ancrage\n(Entité externe)"]

    %% Processus
    SDK(["deedbook-sdk\n(queue FIFO + thread worker)"])
    INGEST(["POST /v1/events\n(auth, validation, masquage, chaînage)"])
    READ(["GET /v1/events\n(auth, pagination, masquage)"])
    VERIFY(["deedbook verify\n(recalcul SHA-256 + Ed25519)"])

    %% Magasins de données
    CS[("chain_state\nid=1, last_seq, last_hash")]
    AE[("audit_events\nSHA-256 chaîné, immuable")]
    AB[("audit_batches\nscellé Ed25519, immuable")]

    %% Flux et frontières de confiance

    APP -->|"emit(event_data)\nnon bloquant"| SDK

    %% FC-1 : réseau non fiable vers moteur
    SDK -->|"POST /v1/events\nBatch JSON + Bearer token"| TB1{ }
    TB1 -. "FC-1 : Internet vers Moteur\nauth token, TLS, limite débit" .- INGEST

    %% FC-2 : moteur vers PostgreSQL, changement de rôle
    INGEST -->|"SELECT FOR UPDATE\nlast_seq + last_hash"| TB2{ }
    TB2 -. "FC-2 : Moteur vers PostgreSQL\nrole deedbook_ingest, triggers immuabilité" .- CS
    INGEST -->|"INSERT audit_events\nSHA-256 chaîné"| AE
    INGEST -->|"INSERT audit_batches\nscellé Ed25519"| AB
    CS -->|"seq_actuel, hash_actuel"| INGEST

    %% Lecture
    APP -->|"GET /v1/events\nBearer token"| READ
    READ -->|"SELECT paginé\ndeedbook_read"| AE
    AE -->|"événements masqués"| READ
    READ -->|"JSON réponse"| APP

    %% Vérification CLI
    ADMIN -->|"deedbook verify"| VERIFY
    VERIFY -->|"SELECT séquentiel\ndeedbook_read"| AE
    VERIFY -->|"SELECT signatures\ndeedbook_read"| AB
    AE -->|"hash + seq"| VERIFY
    AB -->|"signature Ed25519"| VERIFY
    VERIFY -->|"rapport intégrité"| ADMIN

    %% FC-3 : sortie optionnelle vers tiers
    INGEST -->|"POST payload signé\nlast_seq, last_hash, ts, sig"| TB3{ }
    TB3 -. "FC-3 : Moteur vers tiers externe\nsilencieux si indisponible" .- ANCHOR

    %% Styles par type d'élément
    style APP fill:#dbeafe,stroke:#2563eb,color:#1e3a5f
    style ADMIN fill:#dbeafe,stroke:#2563eb,color:#1e3a5f
    style ANCHOR fill:#dbeafe,stroke:#2563eb,color:#1e3a5f
    style SDK fill:#d1fae5,stroke:#059669,color:#065f46
    style INGEST fill:#d1fae5,stroke:#059669,color:#065f46
    style READ fill:#d1fae5,stroke:#059669,color:#065f46
    style VERIFY fill:#d1fae5,stroke:#059669,color:#065f46
    style CS fill:#fef9c3,stroke:#ca8a04,color:#713f12
    style AE fill:#fef9c3,stroke:#ca8a04,color:#713f12
    style AB fill:#fef9c3,stroke:#ca8a04,color:#713f12
    style TB1 fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
    style TB2 fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
    style TB3 fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
```

### Frontières de confiance et STRIDE

| Frontière | Description | STRIDE prioritaire |
|---|---|---|
| **FC-1** : App vers Moteur | Données non fiables entrent via HTTPS. Le token Bearer identifie l'appelant. | Spoofing (auth token), Tampering (validation Pydantic), DoS (100 evts / 256 Ko) |
| **FC-2** : Moteur vers PostgreSQL | Changement de privilège vers le rôle `deedbook_ingest` (INSERT seul). Les triggers bloquent toute mutation. | Tampering (triggers immuabilité), Elevation (moindre privilège) |
| **FC-3** : Moteur vers tiers externe | Flux sortant optionnel. L'ingestion n'est jamais bloquée si le serveur d'ancrage est indisponible. | Repudiation (preuve temporelle tierce), DoS (tolérance panne réseau) |

---

## 2. Vue d'Ensemble des Composants & Relations

`deedbook` isole strictement les responsabilités entre l'application émettrice, l'API d'ingestion et de consultation, et la base de données PostgreSQL durcie.

```mermaid
graph TB
    subgraph HostApp["Application Hôte (Untrusted / Trusted)"]
        AppLogic["Logique Métier"]
        SDK["deedbook-sdk (Queue Mémoire Bornée + Thread Worker)"]
        AppLogic -->|emit non bloquant| SDK
    end

    subgraph API["Moteur deedbook (FastAPI)"]
        IngestEP["POST /v1/events (Ingestion atomique)"]
        ReadEP["GET /v1/events (Consultation paginée / Unitaire)"]
        MaskEngine["Moteur de Masquage (HMAC-SHA256 salé / Redact / Mask)"]
        ChainEngine["Moteur de Chaînage (SHA-256 + Signatures Ed25519)"]
        
        IngestEP --> MaskEngine --> ChainEngine
    end

    subgraph CLI["CLI deedbook"]
        CmdVerify["deedbook verify (Contrôle d'intégrité)"]
        CmdDoctor["deedbook doctor (Audit des droits et horloge)"]
        CmdInit["deedbook init (Migrations et rôles)"]
    end

    subgraph Storage["PostgreSQL (deedbook)"]
        RoleIngest["Rôle deedbook_ingest (INSERT seul, SELECT interdit)"]
        RoleRead["Rôle deedbook_read (SELECT seul)"]
        Triggers["Triggers reject_mutation (Immutabilité stricte)"]
        ChainState["deedbook.chain_state (id=1, FOR UPDATE O(1))"]
        AuditBatches["deedbook.audit_batches (Lots scellés Ed25519)"]
        AuditEvents["deedbook.audit_events (Événements chaînés SHA-256)"]

        RoleIngest -->|SELECT ... FOR UPDATE| ChainState
        RoleIngest -->|INSERT| AuditBatches
        RoleIngest -->|INSERT| AuditEvents
        RoleRead -->|SELECT| AuditEvents
        Triggers -.->|Bloque UPDATE/DELETE/TRUNCATE| AuditEvents
        Triggers -.->|Bloque UPDATE/DELETE/TRUNCATE| AuditBatches
    end

    SDK -->|HTTPS / Bearer App Token| IngestEP
    ChainEngine --> RoleIngest
    ReadEP --> RoleRead
    CmdVerify --> RoleRead
```

### Frontières de sécurité fondamentales

1. **Contrat Zéro Plantage Hôte** : Le SDK Python s'exécute dans l'application cliente. Il utilise une file d'attente FIFO bornée (`maxsize=10000`) et un thread démon d'arrière-plan. Toute panne réseau ou indisponibilité du serveur `deedbook` est absorbée silencieusement sans jamais bloquer ou faire échouer l'application hôte.
2. **Moindres Privilèges PostgreSQL** :
   - Le rôle `deedbook_ingest` ne dispose d'aucun privilège de lecture (`SELECT`) sur les tables `audit_events` et `audit_batches`. Il ne peut ni lire ce qui a été journalisé, ni altérer l'historique existant.
   - Le rôle `deedbook_read` ne dispose que du privilège de consultation (`SELECT`) et ne peut exécuter aucune écriture ou modification.
3. **Immuabilité Applicative et Base** : Des triggers PL/pgSQL (`reject_mutation`) interdisent toute opération `UPDATE`, `DELETE` ou `TRUNCATE` sur les tables du registre, y compris pour le compte d'administration.

---

## 3. Cycle Transactionnel d'Ingestion & Chaînage

L'ingestion s'opère par lots atomiques et idempotents, garantissant la continuité absolue de la séquence d'intégrité sans condition de course (*race condition*).

```mermaid
sequenceDiagram
    autonumber
    participant App as Application Hôte
    participant SDK as deedbook-sdk
    participant API as FastAPI (/v1/events)
    participant DB_CS as deedbook.chain_state
    participant DB_AE as deedbook.audit_events & batches

    App->>SDK: emit(event_data)
    Note over SDK: Queue FIFO bornée en RAM.<br/>Zéro plantage hôte garanti.
    SDK-->>App: Retour immédiat (Non-bloquant)

    Note over SDK: Thread worker batching (max 100 evts ou 2s)
    SDK->>API: POST /v1/events (Batch JSON + Bearer token)

    API->>API: 1. Vérification auth token (SHA-256 vs deedbook.apps)
    API->>API: 2. Validation Pydantic stricte v1.0
    API->>API: 3. Masquage des champs sensibles (HMAC / Redact)

    rect rgb(240, 248, 255)
        Note over API,DB_AE: Transaction PostgreSQL atomique
        API->>DB_CS: SELECT last_seq, last_hash FROM chain_state WHERE id=1 FOR UPDATE
        DB_CS-->>API: (seq_actuel, hash_actuel)
        
        loop Pour chaque événement du lot
            API->>API: seq += 1
            API->>API: hash = SHA-256(prev_hash : seq : canonical_json)
            API->>API: prev_hash = hash
        end

        API->>API: Signature Ed25519 des métadonnées du lot
        API->>DB_AE: INSERT INTO audit_batches (...) ON CONFLICT DO NOTHING RETURNING 1
        
        alt Si nouveau lot (RETURNING 1)
            API->>DB_CS: UPDATE chain_state SET last_seq=..., last_hash=...
            API->>DB_AE: INSERT INTO audit_events (...) ON CONFLICT DO NOTHING
        end
    end

    API-->>SDK: 202 Accepted {batch_id, received_count, untrusted_app}
```

### Mécanismes clés de l'ingestion

- **Verrou ligne en $O(1)$** : Au lieu de calculer `SELECT MAX(integrity_seq) FROM audit_events` qui se dégraderait avec le volume de données, `deedbook` verrouille la ligne unique de la table `deedbook.chain_state` (`WHERE id = 1 FOR UPDATE`). Ce verrouillage sérialise les requêtes concurrentes en temps constant.
- **Idempotence stricte** : Si un lot est réémis (timeout réseau, rejeu), `ON CONFLICT DO NOTHING` évite toute insertion en double et préserve la chaîne sans altérer l'état.

---

## 4. Topologie Cryptographique : SHA-256 & Signatures Ed25519

La preuve d'intégrité de `deedbook` repose sur une double protection : un chaînage continu événement-par-événement (SHA-256) combiné à un scellement asymétrique par lot (Ed25519).

```mermaid
flowchart LR
    subgraph Genesis["Origine"]
        G0["GENESIS_HASH<br/>(64 zéros)"]
    end

    subgraph Batch1["Lot B1 (Signé Ed25519)"]
        E1["Événement #1<br/>seq: 1<br/>prev_hash: GENESIS<br/>hash: H1"]
        E2["Événement #2<br/>seq: 2<br/>prev_hash: H1<br/>hash: H2"]
        SigB1["Signature Ed25519 B1<br/>couvre: first_seq=1, last_seq=2,<br/>first_hash=H1, last_hash=H2"]
    end

    subgraph Batch2["Lot B2 (Signé Ed25519)"]
        E3["Événement #3<br/>seq: 3<br/>prev_hash: H2<br/>hash: H3"]
        E4["Événement #4<br/>seq: 4<br/>prev_hash: H3<br/>hash: H4"]
        SigB2["Signature Ed25519 B2<br/>couvre: first_seq=3, last_seq=4,<br/>first_hash=H3, last_hash=H4"]
    end

    G0 --> E1
    E1 --> E2
    E2 --> E3
    E3 --> E4

    E1 -.-> SigB1
    E2 -.-> SigB1
    E3 -.-> SigB2
    E4 -.-> SigB2
```

### Formule de calcul de l'empreinte canonique

Pour chaque événement $i$ de séquence $\text{seq}_i$, l'empreinte $\text{event\_hash}_i$ est calculée par :

$$\text{event\_hash}_i = \text{SHA-256}(\text{prev\_hash}_i : \text{seq}_i : \text{canonical\_json}(\text{event}_i))$$

Où $\text{canonical\_json}$ est une sérialisation normalisée UTF-8 respectant l'ordre alphabétique des 24 clés canoniques (spec v1.0), sans aucun espace (`separators=(',', ':')`), garantissant un résultat déterministe quel que soit l'environnement.

### Scellement du lot par signature Ed25519

Chaque lot est scellé par une signature cryptographique asymétrique calculée sur le payload textuel canonique suivant :

```text
deedbook:batch:v1:<batch_id>:<app>:<schema_version>:<event_count>:<first_seq>:<last_seq>:<first_hash>:<last_hash>
```

Cette signature apporte la non-répudiation et garantit que les bornes de séquence et de hash n'ont pas été modifiées ou réordonnées.

---

## 5. Vérification d'Intégrité (`deedbook verify`)

La commande CLI `deedbook verify` effectue une vérification séquentielle complète et indépendante :
1. **Continuité de séquence** : Contrôle que `integrity_seq` commence à 1 et s'incrémente de 1 en 1 sans aucun trou.
2. **Chaînage SHA-256** : Pour chaque événement, vérification que `prev_hash` correspond à l'empreinte précédente et recalcul exact de `event_hash`.
3. **Validité des signatures Ed25519** : Pour chaque lot dans `audit_batches`, recalcul de la charge utile de scellement et vérification de la signature numérique via la clé publique Ed25519.
4. **Cohérence volumétrique** : Validation que le nombre d'événements rattachés au lot correspond exactement à `event_count`.

---

## 6. Cartographie du Modèle de Menace & Barrières de Défense (S1 à S6)

Le diagramme ci-dessous illustre les points d'attaque potentiels (scénarios S1 à S6 du [Modèle de Menace](modele-de-menace.md)) et les barrières architecturales qui les neutralisent :

```mermaid
graph TD
    subgraph Attaquants["Scénarios de Menace"]
        S1["S1 : App compromise<br/>(tente d'effacer/modifier)"]
        S2["S2 : Accès direct DB<br/>(écriture hors appli)"]
        S3["S3 : Erreur d'admin<br/>(mauvais droit/jeton)"]
        S4["S4 : Fuite de secrets<br/>(tentative de commit/leak)"]
        S5["S5 : Altération interne<br/>(modification ligne DB)"]
        S6["S6 : Charge malveillante<br/>(XSS, SQLi, déni mémoire)"]
    end

    subgraph DefenseL1["Barrière 1 : Frontière Réseau & Ingestion"]
        HookSec["Hook Git pre-commit<br/>(bloque .env et clés en clair)"]
        PydanticVal["Validation Pydantic v1.0<br/>(extra='forbid', bornes 256 Ko / 100 evts)"]
        MaskingEng["Masquage HMAC-SHA256 salé<br/>(anonymise à la source)"]
    end

    subgraph DefenseL2["Barrière 2 : Frontière Rôles & Base PostgreSQL"]
        RoleIngestPerm["Rôle deedbook_ingest<br/>(INSERT seul, SELECT/UPDATE interdit)"]
        TriggersImm["Triggers PL/pgSQL reject_mutation<br/>(bloque UPDATE/DELETE/TRUNCATE)"]
        PgAuditEngine["pgAudit & Corrélation<br/>(rapprochement journal base / appli)"]
        DoctorAudit["deedbook doctor<br/>(audit des droits réels has_table_privilege)"]
    end

    subgraph DefenseL3["Barrière 3 : Preuve Cryptographique & Vérification"]
        ChainVerify["deedbook verify<br/>(recalcul continu SHA-256 + Ed25519)"]
        AnchorTarget["Ancrage Externe anchor_url<br/>(preuve temporelle tierce)"]
    end

    S4 -.->|Bloqué par ATK-08| HookSec
    S6 -.->|Bloqué par ATK-06, ATK-07| PydanticVal
    S6 -.->|Secret masqué| MaskingEng

    S1 -.->|Bloqué par ATK-01| RoleIngestPerm
    S1 -.->|Bloqué par ATK-02, ATK-03| TriggersImm
    S2 -.->|Détecté par ATK-05| PgAuditEngine
    S3 -.->|Bloqué par ATK-09| DoctorAudit

    S5 -.->|Bloqué par ATK-03| TriggersImm
    S5 -.->|Détecté par ATK-04| ChainVerify
    S5 -.->|Neutralisé par| AnchorTarget
```

### Correspondance des Barrières & Tests d'Attaque

| Scénario | Vecteur d'Attaque | Barrière Architecturale | Test Validé |
|---|---|---|---|
| **S1** | L'application émettrice compromise tente un `UPDATE` ou `DELETE` | Rôle `deedbook_ingest` sans SELECT/mutation + trigger d'immutabilité | **ATK-01**, **ATK-02** |
| **S2** | Écriture SQL directe sur la base de données métier | pgAudit + réconciliation par `correlation_id` | **ATK-05** (V1) |
| **S3** | L'opérateur accorde trop de droits ou saisit un nom d'application corrompu | `deedbook doctor` vérifie `has_table_privilege` + regex de validation stricte | **ATK-09** |
| **S4** | Clé privée ou fichier `.env` ajouté au dépôt Git | Hook `.githooks/pre-commit` scannant les diffs et rejetant les motifs sensibles | **ATK-08** |
| **S5** | Un attaquant ayant un accès DB modifie un hash ou une séquence | Détection par `verify_chain` (rupture de séquence ou hash mismatch) | **ATK-03**, **ATK-04** |
| **S6** | Injection de script XSS, de commande SQL ou d'un lot géant | Requêtes SQL paramétrées, validation de profondeur (4 max) et limites (256 Ko, 100 evts) | **ATK-06**, **ATK-07** |

