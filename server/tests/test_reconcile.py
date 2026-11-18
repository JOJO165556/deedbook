"""Tests pour l'analyseur pgAudit et le moteur de réconciliation (reconcile.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

from deedbook.reconcile import (
    PgAuditEntry,
    ReconciliationReport,
    parse_pgaudit_line,
    parse_pgaudit_log,
    reconcile_pgaudit,
)


def test_parse_pgaudit_line_valide():
    """parse_pgaudit_line extrait correctement les champs d'un log pgAudit standard."""
    line = (
        "LOG:  AUDIT: SESSION,1,1,WRITE,INSERT,TABLE,public.articles,"
        "INSERT INTO public.articles (title) VALUES ('test') "
        "/* correlation_id: corr-123 */,<not logged>"
    )
    entry = parse_pgaudit_line(line)
    assert entry is not None
    assert entry.statement_id == 1
    assert entry.substatement_id == 1
    assert entry.audit_class == "WRITE"
    assert entry.command == "INSERT"
    assert entry.object_type == "TABLE"
    assert entry.object_name == "public.articles"
    assert entry.correlation_id == "corr-123"


def test_parse_pgaudit_line_sans_correlation_id():
    """Une requête directe sans commentaire porte correlation_id = None."""
    line = (
        "LOG:  AUDIT: SESSION,2,1,WRITE,UPDATE,TABLE,public.users,"
        "UPDATE public.users SET is_admin = true WHERE id = 1,<not logged>"
    )
    entry = parse_pgaudit_line(line)
    assert entry is not None
    assert entry.command == "UPDATE"
    assert entry.correlation_id is None


def test_parse_pgaudit_line_ignore_lignes_non_audit():
    """Les lignes de logs système postgres sans préfixe AUDIT retournent None."""
    assert parse_pgaudit_line("LOG:  database system is ready to accept connections") is None
    assert parse_pgaudit_line("") is None


def test_parse_pgaudit_log_plusieurs_lignes():
    """parse_pgaudit_log analyse un flux multiligne de logs."""
    log_text = "\n".join(
        [
            "2026-11-18 00:00:01 UTC [100] LOG:  AUDIT: SESSION,1,1,READ,SELECT,TABLE,"
            "public.articles,SELECT * FROM public.articles,<not logged>",
            "2026-11-18 00:00:02 UTC [100] LOG:  AUDIT: SESSION,2,1,WRITE,INSERT,TABLE,"
            "public.articles,INSERT INTO public.articles (title) VALUES ('a') "
            "/* correlation_id: corr-1 */,<not logged>",
            "2026-11-18 00:00:03 UTC [100] LOG:  statement: SELECT 1",
        ]
    )
    entries = parse_pgaudit_log(log_text)
    assert len(entries) == 2
    assert entries[0].audit_class == "READ"
    assert entries[1].audit_class == "WRITE"
    assert entries[1].correlation_id == "corr-1"


def test_reconcile_pgaudit_detecte_ecriture_orpheline_sans_correlation_id():
    """Une écriture directe sans correlation_id est immédiatement signalée orpheline."""
    entry = PgAuditEntry(
        statement_id=1,
        substatement_id=1,
        audit_class="WRITE",
        command="UPDATE",
        object_type="TABLE",
        object_name="public.users",
        statement="UPDATE public.users SET admin=true",
        correlation_id=None,
    )
    conn = MagicMock()

    report: ReconciliationReport = reconcile_pgaudit(conn, [entry])
    assert report.total_entries == 1
    assert report.writes_analyzed == 1
    assert report.matched_events == 0
    assert len(report.orphans) == 1
    assert "aucun correlation_id" in report.orphans[0].reason.lower()


def test_reconcile_pgaudit_detecte_ecriture_orpheline_correlation_inconnue():
    """Une écriture avec correlation_id absent de deedbook est signalée orpheline."""
    entry = PgAuditEntry(
        statement_id=1,
        substatement_id=1,
        audit_class="WRITE",
        command="INSERT",
        object_type="TABLE",
        object_name="public.orders",
        statement="INSERT INTO public.orders VALUES (1) /* correlation_id: faux-id */",
        correlation_id="faux-id",
    )
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None

    report: ReconciliationReport = reconcile_pgaudit(conn, [entry])
    assert len(report.orphans) == 1
    assert "introuvable" in report.orphans[0].reason.lower()


def test_reconcile_pgaudit_valide_ecriture_reconciliee():
    """Une écriture dont le correlation_id existe dans deedbook est validée."""
    entry = PgAuditEntry(
        statement_id=1,
        substatement_id=1,
        audit_class="WRITE",
        command="INSERT",
        object_type="TABLE",
        object_name="public.articles",
        statement="INSERT INTO public.articles VALUES ('A') /* correlation_id: corr-valid */",
        correlation_id="corr-valid",
    )
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = ("evt-1", "articles")

    report: ReconciliationReport = reconcile_pgaudit(conn, [entry])
    assert len(report.orphans) == 0
    assert report.matched_events == 1


def test_reconcile_pgaudit_ignore_lectures():
    """Les opérations de lecture READ ne sont pas comptées comme écritures."""
    entry = PgAuditEntry(
        statement_id=1,
        substatement_id=1,
        audit_class="READ",
        command="SELECT",
        object_type="TABLE",
        object_name="public.articles",
        statement="SELECT * FROM public.articles",
        correlation_id=None,
    )
    conn = MagicMock()

    report: ReconciliationReport = reconcile_pgaudit(conn, [entry])
    assert report.total_entries == 1
    assert report.writes_analyzed == 0
    assert len(report.orphans) == 0


def test_cmd_reconcile_subcommand_existe():
    """La commande 'deedbook reconcile' est enregistrée dans le CLI."""
    import pytest

    from deedbook.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["reconcile", "--help"])
    assert exc.value.code == 0
