"""CLI deedbook : init, doctor, verify, project add"""

from __future__ import annotations

import argparse
import sys


def cmd_init(_args: argparse.Namespace) -> int:
    from deedbook.admin import init

    return init()


def cmd_doctor(_args: argparse.Namespace) -> int:
    from deedbook.admin import doctor

    return doctor()


def cmd_verify(_args: argparse.Namespace) -> int:
    print("deedbook verify : non implémenté (chaînage V1)")
    return 1


def cmd_project_add(args: argparse.Namespace) -> int:
    from deedbook.admin import add_project

    return add_project(args.name)


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
