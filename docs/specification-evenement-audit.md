# Spécification de l'événement d'audit

Version 1.0 - statut : validée pour V0
Périmètre : format d'un événement unitaire et d'un lot. Le chaînage
cryptographique et la signature des lots relèvent d'une spec séparée (V1) ;
les champs d'intégrité sont prévus dès maintenant pour ne pas casser le
format.

## 1. Principes

- **JSON uniquement**, UTF-8, aucun champ binaire (les valeurs avant/après
  sont des objets JSON).
- **Validation stricte** : tout champ inconnu ou manquant est rejeté. Pas de
  tolérance silencieuse - un producteur qui dévie du format doit le savoir.
- **L'horodatage vient du producteur** pour l'événement métier, et du moteur
  à la réception (`received_at`) pour la preuve de réception.
- **Le masquage se fait à la source** (SDK) et est revérifié par le moteur :
  un champ déclaré sensible ne doit jamais arriver en clair.
- **Idempotence** : chaque événement porte une clé d'idempotence ; un rejeu
  du même lot ne crée pas de doublon.

## 2. Événement unitaire

```json
{
  "schema_version": "1.0",
  "event_id": "01932e8a-7c4f-7b2a-9d1e-3f5a6b7c8d9e",
  "idempotency_key": "req_8f3a2c1d-...",
  "occurred_at": "2026-11-08T14:32:07.412Z",

  "actor": {
    "end_user": "user_42",
    "type": "human",
    "role": "editor"
  },
  "service_account": "app_svc",
  "origin": {
    "app": "monapp",
    "component": "api",
    "ip": "10.0.0.5",
    "session_id": "sess_91",
    "request_id": "req_8f3a2c1d"
  },

  "correlation_id": "corr_7d2e...",

  "action": "update",
  "resource": {
    "type": "record",
    "name": "articles",
    "id": "art_123"
  },
  "result": {
    "status": "success"
  },

  "change": {
    "before": {"title": "Ancien", "price": 10},
    "after": {"title": "Nouveau", "price": 12}
  },

  "integrity": {
    "seq": null,
    "event_hash": null,
    "prev_hash": null
  }
}
```

### 2.1 Identification

| Champ | Format | Règle |
|---|---|---|
| `schema_version` | string `MAJEUR.MINEUR` | Requis. MAJEUR = rupture, MINER = ajout compatible. Le moteur accepte sa version et la mineure précédente |
| `event_id` | UUIDv7 (RFC 9562), forme canonique avec tirets | Unique, généré par le producteur. Sert aussi de clé de déduplication |
| `idempotency_key` | string 8–128 | Clé de rejeu sans doublon au niveau du lot et de l'événement |

### 2.2 Horodatage

| Champ | Format | Règle |
|---|---|---|
| `occurred_at` | RFC 3339, millisecondes, offset `Z` | Heure de l'action côté application. Rejet si dans le futur de plus de 5 min (tolérance d'horloge) |
| `received_at` | RFC 3339 serveur | Ajouté par le moteur à la réception, jamais fourni par le client |

### 2.3 Acteur et origine

`actor.end_user` : identifiant de l'utilisateur final - c'est la réponse à
« qui a fait quoi ». `actor.type` ∈ `human | service | agent | system`.
`actor.role` : rôle applicatif au moment de l'action (optionnel).
`service_account` : compte technique ayant exécuté l'opération (requis si
`actor.type != human`).

`origin.app` : nom du projet déclaré via `deedbook project add`. Politique
tolérante : un événement d'une app inconnue est accepté mais marqué
`untrusted_app: true` - jamais de perte d'événement pour un oubli
d'enregistrement. Le drapeau est visible en recherche.
`origin.ip` : IPv4/IPv6 ou `unknown`. `origin.request_id` : identifiant de la
requête HTTP, base de la corrélation.

### 2.4 Corrélation

`correlation_id` : identifiant commun propagé de l'application jusqu'à la
base (chaque requête DB exécutée dans son cadre porte le même identifiant -
réservé à une variable de session PostgreSQL, spec V0 à détailler lors de
l'implémentation SDK).

### 2.5 Action et ressource

`action` ∈ liste fermée :

```
read, create, update, delete, export,
login, logout, authz_change, config_change
```

`resource.type` ∈ `table | record | view | function | other`.
`resource.name` : nom qualifié (`schéma.table` pour `table`).
`resource.id` : identifiant de l'enregistrement, optionnel.

### 2.6 Résultat

`result.status` ∈ `success | denied | error`.
Si `denied` ou `error` : `result.code` (string, ex. `PERMISSION_DENIED`,
`CONSTRAINT_VIOLATION`) et `result.message` (tronqué à 500 caractères,
champs sensibles masqués).

### 2.7 Changement

`change.before` / `change.after` : objets JSON des colonnes modifiées.
- Obligatoire pour `create` (after seul), `update` (les deux), `delete`
  (before seul) quand la ressource est `record` ou `table`.
- Interdit pour `read`, `export`, `login`.
- Profondeur max 4, taille max 8 Ko sérialisé par côté.
- Les champs listés dans `deedbook.toml [masking] fields` (par ressource ou
  glob `table.colonne`) sont remplacés par leur empreinte avant envoi.

## 3. Règles de masquage

Trois stratégies, déclarées par champ dans `deedbook.toml` :

```toml
[masking]
fields = [
  { resource = "users", field = "password_hash", strategy = "redact" },
  { resource = "users", field = "email", strategy = "hash" },
  { resource = "*", field = "*_secret", strategy = "mask", keep = 4 },
]
```

| Stratégie | Effet | Usage |
|---|---|---|
| `redact` | Valeur remplacée par `"[redacted]"` | Secrets, mots de passe |
| `hash` | HMAC-SHA256 tronqué à 16 hex, salé par `event_id` | Rechercher sans stocker (ex. email) |
| `mask` | Début conservé (`keep` caractères), reste `*` | Cartes, téléphones |

Règles :
- Le masquage s'applique **avant sérialisation** du lot, côté SDK.
- Le moteur **re-masque** toute valeur correspondant à un champ déclaré :
  un producteur qui oublie le SDK ne peut pas faire fuiter le champ.
- Les champs masqués ne sont jamais journalisés en clair, y compris dans
  `result.message`.
- Un champ `hash` reste corrélable entre événements (même valeur → même
  empreinte) mais irréversible sans la clé HMAC du moteur.

## 4. Lot (batch)

```json
{
  "schema_version": "1.0",
  "batch_id": "01932e8a-...",
  "app": "monapp",
  "sent_at": "2026-11-08T14:32:08.001Z",
  "events": [ { ... }, { ... } ]
}
```

Règles du lot :
- `POST /v1/events`, authentification par jeton applicatif (≠ jeton admin).
- Tailles : 1–100 événements, ≤ 256 Ko sérialisé (aligné sur
  `deedbook.toml [ingestion]`).
- Le lot est **atomique** : tout ou rien. Un événement invalide rejette le
  lot entier avec `422` et le détail de l'erreur par index.
- La réponse est `202 Accepted` avec `batch_id` et `received_count` ; le
  moteur ne garantit pas l'ordre inter-lots (le `seq` du chaînage V1
  rétablit l'ordre d'ingestion).

## 5. Erreurs de validation

```json
{
  "error": "validation_failed",
  "detail": [
    {"index": 3, "field": "occurred_at", "reason": "format RFC3339 invalide"}
  ]
}
```

Codes : `validation_failed` (422), `unauthorized` (401), `unknown_app` →
accepté avec drapeau (202 quand même), `batch_too_large` (413),
`rate_limited` (429).

## 6. Versioning

- `schema_version` MAJEUR incrémenté sur toute rupture (champ renommé,
  sémantique changée, champ requis ajouté).
- MINER pour ajout de champ optionnel ou valeur d'énumération.
- Le moteur conserve les événements dans leur version d'origine ; la
  restitution normalise à la version demandée par le client de lecture.
- Une spec mineure ne doit jamais rendre un ancien événement illisible.

## 7. Ce que cette spec ne couvre pas (étapes suivantes)

- Calcul de `event_hash` / `prev_hash` et chaînage : spec V1.
- Signature du lot (clé dédiée) : spec V1.
- Variables de session PostgreSQL pour la corrélation base : détail
  d'implémentation SDK en V0.
- Événements côté base (pgAudit) : format d'import défini en V1 avec les
  écritures orphelines.
