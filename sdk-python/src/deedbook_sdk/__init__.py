"""Kit d'intégration deedbook (Python).

Contrat : zéro plantage hôte - aucune exception ne remonte vers
l'application ; en cas de panne du moteur, file locale durable et rejeu
sans doublon.
"""

from deedbook_sdk.client import AuditClient, disable, enable

__all__ = ["AuditClient", "disable", "enable"]
