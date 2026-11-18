# Politique de sécurité

## Signalement responsable de vulnérabilité

La sécurité et la détection d'altération sont la raison d'être de Deedbook. Si vous découvrez une faille de sécurité ou une vulnérabilité cryptographique, je vous remercie de me la signaler de manière responsable et confidentielle avant toute divulgation publique.

### Comment signaler une vulnérabilité

Ne créez pas de ticket ou d'issue publique sur GitHub pour signaler une vulnérabilité.

Veuillez utiliser l'un des canaux suivants :
1. **GitHub Security Advisories** : ouvrez un rapport privé via l'onglet [Security / Advisories](https://github.com/JOJO165556/deedbook/security/advisories/new) du dépôt GitHub (méthode privilégiée lorsque le signalement privé est actif).
2. **Courriel direct** : écrivez à `hounkpatijosue2020@gmail.com` avec pour objet `[SECURITY] Vulnérabilité Deedbook`.

Veuillez inclure dans votre rapport :
* La version de Deedbook concernée (serveur ou SDK) ou le commit de la branche `main`.
* La description détaillée de la vulnérabilité et son impact potentiel.
* Les étapes pour reproduire le problème ou un scénario de démonstration (PoC).
* Tout correctif ou atténuation suggéré.

### Engagements et délais

Je suis l'unique mainteneur et je travaille sur ce projet pendant mon temps libre. Je m'engage au mieux :
* **Accusé de réception** : sous 7 jours.
* **Évaluation initiale** : sous 14 jours.
* **Divulgation coordonnée** : convenue d'un commun accord sous 90 jours au plus (prolongeable d'un commun accord selon la complexité du correctif).

## Versions prises en charge

Projet expérimental : seuls la dernière version publiée et la branche `main` reçoivent des correctifs.

## Règles de recherche et environnement de test

* **Instance isolée uniquement** : vos recherches et tests doivent être réalisés exclusivement sur votre propre instance locale ou sur un environnement que vous contrôlez. Ne ciblez jamais des services ou déploiements tiers.
* **Pas de récompense financière** : aucun programme de prime aux bogues (bug bounty) n'est proposé. En revanche, les personnes signalant une vulnérabilité de manière constructive sont remerciées publiquement dans les notes de version si elles le souhaitent.
* **Bonne foi** : je ne chercherai pas à engager de poursuites contre les chercheurs qui agissent de bonne foi et dans le strict respect de ce cadre.

## Périmètre et modèle de menace

Avant de soumettre un rapport, veuillez consulter le [Modèle de menace](docs/modele-de-menace.md).

### Dans le périmètre :
* Altération, suppression ou réordonnancement d'événements sans détection lors de la commande `deedbook verify`.
* Échappement de contexte ou injection SQL dans le pipeline d'ingestion.
* Contournement de l'isolation des rôles `deedbook_ingest` ou `deedbook_read`.
* Fuite de données censées être masquées ou hachées.
* Déni de service causé par une faille du code (entrée malformée, boucle CPU ou allocation anormale qui plante ou bloque le moteur de façon persistante).

### Hors périmètre :
* Déni de service purement volumétrique (saturation de la bande passante réseau ou inondation de requêtes sans faille logicielle sous-jacente).
* Vulnérabilités situées dans des dépendances tierces (FastAPI, Psycopg, PostgreSQL, Uvicorn, etc.), à signaler en amont à leurs projets respectifs.
* Mauvaises configurations d'un déploiement particulier (clés secrètes par défaut conservées en production, ports internes exposés sans pare-feu, etc.).
* Compromission conjointe par un attaquant disposant d'un accès administrateur total (root / superutilisateur PostgreSQL) ET de la clé privée de signature Ed25519 du serveur (scénario ATK-04).
* Événements falsifiés directement en base sans passer par le moteur d'audit lorsqu'aucun ancrage externe ou rapprochement pgAudit n'est activé (limite connue de conception, voir le modèle de menace).
* Ingénierie sociale ou hameçonnage.
