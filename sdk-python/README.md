# deedbook-sdk (Python)

Kit d'intégration côté application. Couche mince au-dessus de l'API du
moteur : propagation de l'identifiant de corrélation, envoi par lots, file
locale en cas de panne, masquage des champs sensibles.

## Contrat

- **Zéro plantage hôte** : aucune exception ne remonte vers l'application.
- Envoi asynchrone, délais courts ; file locale durable + rejeu sans doublon
  (clé d'idempotence par événement).
- Masquage des champs déclarés sensibles avant stockage.

L'interface HTTP du moteur reste le contrat de référence — un script peut
l'appeler directement sans ce SDK.
