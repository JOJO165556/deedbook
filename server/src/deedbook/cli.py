"""CLI deedbook : init, doctor, verify, anchor, archive, serve, project add."""

from __future__ import annotations

import argparse
import sys


def cmd_init(_args: argparse.Namespace) -> int:
    from deedbook.admin import init

    return init()


def cmd_doctor(_args: argparse.Namespace) -> int:
    from deedbook.admin import doctor

    return doctor()


def cmd_archive(args: argparse.Namespace) -> int:
    from datetime import date
    from pathlib import Path

    from deedbook.admin import connect, database_url
    from deedbook.archive import archive_before, save_checkpoint
    from deedbook.config import get_settings

    try:
        before = date.fromisoformat(args.before)
    except ValueError:
        print(f"archive : date invalide '{args.before}' (format attendu : YYYY-MM-DD)")
        return 1

    output = Path(args.output)
    settings = get_settings()
    signing_key = settings.signing_key.get_secret_value() if settings.signing_key else ""

    with connect(database_url()) as conn:
        count = archive_before(conn, before=before, signing_key_b64=signing_key, output_path=output)
        if count == 0:
            print(f"archive : aucun evenement anterieur a {before}")
            return 0
        save_checkpoint(
            conn,
            archived_before=before,
            event_count=count,
            last_seq=0,
            last_hash="",
            archive_path=str(output.resolve()),
        )

    print(f"archive : {count} evenements -> {output}")
    return 0


def cmd_purge(args: argparse.Namespace) -> int:
    from datetime import date

    from deedbook.admin import connect, database_url
    from deedbook.archive import purge_archived

    try:
        before = date.fromisoformat(args.before)
    except ValueError:
        print(f"purge : date invalide '{args.before}' (format attendu : YYYY-MM-DD)")
        return 1

    with connect(database_url()) as conn:
        try:
            count = purge_archived(conn, before=before)
        except ValueError as exc:
            print(f"purge : {exc}")
            return 1

    print(f"purge : {count} evenements supprimes (before={before})")
    return 0


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

    arc = sub.add_parser("archive", help="Archive les evenements expires dans un fichier signe")
    arc.add_argument("--before", required=True, help="Date limite ISO 8601 (YYYY-MM-DD)")
    arc.add_argument("--output", default="deedbook-archive.json", help="Fichier de sortie")
    arc.set_defaults(func=cmd_archive)

    purge = sub.add_parser("purge", help="Supprime les evenements archives (checkpoint requis)")
    purge.add_argument("--before", required=True, help="Date limite ISO 8601 (YYYY-MM-DD)")
    purge.set_defaults(func=cmd_purge)

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
