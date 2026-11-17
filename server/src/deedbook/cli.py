"""CLI deedbook : init, doctor, verify, anchor, serve, project add."""

from __future__ import annotations

import argparse
import sys


def cmd_init(_args: argparse.Namespace) -> int:
    from deedbook.admin import init

    return init()


def cmd_doctor(_args: argparse.Namespace) -> int:
    from deedbook.admin import doctor

    return doctor()


def cmd_anchor(_args: argparse.Namespace) -> int:
    from deedbook.admin import connect, database_url
    from deedbook.anchor import publish_anchor
    from deedbook.config import get_settings

    settings = get_settings()
    if not settings.anchor_url:
        print("anchor : anchor_url non configurée (DEEDBOOK_ANCHOR_URL), rien a faire")
        return 0

    signing_key = settings.signing_key.get_secret_value() if settings.signing_key else ""
    with connect(database_url()) as conn:
        publish_anchor(conn, anchor_url=settings.anchor_url, signing_key_b64=signing_key)
    print(f"anchor : empreinte publiée vers {settings.anchor_url}")
    return 0


def cmd_verify(_args: argparse.Namespace) -> int:
    from deedbook.admin import connect, database_url
    from deedbook.chain import verify_chain
    from deedbook.config import get_settings

    settings = get_settings()
    signing_key = settings.signing_key.get_secret_value() if settings.signing_key else None

    with connect(database_url()) as conn:
        report = verify_chain(conn, signing_key_b64=signing_key)

    print(f"Événements vérifiés : {report.events_verified}")
    print(f"Lots vérifiés       : {report.batches_verified}")
    if report.is_valid:
        print("verify : intégrité de la chaîne validée (aucune altération)")
        return 0

    print("verify : ÉCHEC D'INTÉGRITÉ - altérations détectées :")
    for err in report.errors:
        print(f"  - {err}")
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
    sub.add_parser(
        "anchor", help="Publie l'empreinte courante vers le serveur d'ancrage"
    ).set_defaults(func=cmd_anchor)

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
