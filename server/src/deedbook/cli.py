"""CLI deedbook : init, doctor, verify, project add.

Socle : seules les commandes existent. `doctor` valide déjà la
configuration ; le reste arrive avec les phases V0–V3.
"""

from __future__ import annotations

import argparse
import sys


def _not_implemented(name: str) -> int:
    print(f"deedbook {name} : non implémenté (voir feuille de route V0–V3 dans la charte).")
    return 1


def cmd_init(_args: argparse.Namespace) -> int:
    return _not_implemented("init")


def cmd_doctor(_args: argparse.Namespace) -> int:
    from deedbook.config import ConfigError, get_settings, policy

    try:
        settings = get_settings()
    except ConfigError as exc:
        print(exc)
        return 1

    # La politique est vérifiable sans secret
    mods = policy().get("modules", {}).get("enabled", [])
    print(f"Configuration OK — moteur joignable sur le port {settings.port}")
    print(f"Modules activés : {mods or 'aucun'}")
    print("Vérifications restantes (à implémenter) : connexion DB, droits réels,")
    print("présence des clés, horloge synchronisée, destination d'ancrage.")
    return 0


def cmd_verify(_args: argparse.Namespace) -> int:
    return _not_implemented("verify")


def cmd_project_add(args: argparse.Namespace) -> int:
    print(f"deedbook project add {args.name!r} : non implémenté.")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deedbook", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Applique migrations, crée rôles et clés").set_defaults(
        func=cmd_init
    )
    sub.add_parser("doctor", help="Vérifie la configuration et l'environnement").set_defaults(
        func=cmd_doctor
    )
    sub.add_parser("verify", help="Vérifie la chaîne d'intégrité du journal").set_defaults(
        func=cmd_verify
    )

    project = sub.add_parser("project", help="Gestion des projets audités")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    add = project_sub.add_parser("add", help="Enregistre un projet à auditer")
    add.add_argument("name")
    add.set_defaults(func=cmd_project_add)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
