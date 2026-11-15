"""CLI deedbook : init, doctor, verify, serve, project add."""

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


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from deedbook.config import get_settings

    settings = get_settings()
    host = args.host or "127.0.0.1"
    port = args.port or settings.port
    uvicorn.run("deedbook.api:create_app", factory=True, host=host, port=port, reload=args.reload)
    return 0


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

    serve = sub.add_parser("serve", help="Démarre le serveur API FastAPI")
    serve.add_argument("--host", default=None, help="Hôte d'écoute (défaut: 127.0.0.1)")
    serve.add_argument(
        "--port", type=int, default=None, help="Port d'écoute (défaut: DEEDBOOK_PORT ou 8000)"
    )
    serve.add_argument("--reload", action="store_true", help="Rechargement automatique")
    serve.set_defaults(func=cmd_serve)

    project = sub.add_parser("project", help="Gestion des projets audités")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    add = project_sub.add_parser("add", help="Enregistre un projet à auditer")
    add.add_argument("name")
    add.set_defaults(func=cmd_project_add)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
