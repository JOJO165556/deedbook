"""Moteur d'analyse pgAudit et de réconciliation des écritures orphelines (ATK-05)."""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg

logger = logging.getLogger(__name__)

_CORRELATION_RE = re.compile(
    r"(?:/\*\s*correlation_id\s*[:=]\s*([^\s\*]+)\s*\*/|"
    r"--\s*correlation_id\s*[:=]\s*([^\s]+)|"
    r"set_config\s*\(\s*['\"](?:app|deedbook)\.correlation_id['\"]\s*,\s*['\"]([^'\"]+)['\"])",
    re.IGNORECASE,
)

_WRITE_CLASSES = frozenset({"WRITE", "DDL"})
_WRITE_COMMANDS = frozenset({"INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER", "CREATE"})


@dataclass
class PgAuditEntry:
    """Entrée extraite d'une ligne de journalisation pgAudit."""

    statement_id: int
    substatement_id: int
    audit_class: str
    command: str
    object_type: str
    object_name: str
    statement: str
    correlation_id: str | None = None


@dataclass
class OrphanWrite:
    """Écriture base de données détectée sans justification applicative."""

    entry: PgAuditEntry
    reason: str


@dataclass
class ReconciliationReport:
    """Bilan du rapprochement entre journaux pgAudit et événements deedbook."""

    total_entries: int = 0
    writes_analyzed: int = 0
    matched_events: int = 0
    orphans: list[OrphanWrite] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return len(self.orphans) == 0


def _extract_correlation_id(statement: str) -> str | None:
    match = _CORRELATION_RE.search(statement)
    if not match:
        return None
    for group in match.groups():
        if group:
            return group.strip()
    return None


def parse_pgaudit_line(line: str) -> PgAuditEntry | None:
    """Analyse une ligne de log PostgreSQL et extrait l'enregistrement pgAudit si présent."""
    marker = "AUDIT: "
    idx = line.find(marker)
    if idx == -1:
        return None

    csv_data = line[idx + len(marker) :].strip()
    reader = csv.reader(io.StringIO(csv_data))
    try:
        fields = next(reader)
    except (StopIteration, csv.Error):
        return None

    if len(fields) < 8:
        return None

    try:
        stmt_id = int(fields[1])
        substmt_id = int(fields[2])
    except ValueError:
        return None

    audit_class = fields[3].strip().upper()
    command = fields[4].strip().upper()
    object_type = fields[5].strip().upper()
    object_name = fields[6].strip()
    statement = fields[7].strip()

    correlation_id = _extract_correlation_id(statement)

    return PgAuditEntry(
        statement_id=stmt_id,
        substatement_id=substmt_id,
        audit_class=audit_class,
        command=command,
        object_type=object_type,
        object_name=object_name,
        statement=statement,
        correlation_id=correlation_id,
    )


def parse_pgaudit_log(content: str) -> list[PgAuditEntry]:
    """Extrait tous les événements pgAudit d'un flux de logs textuel."""
    entries: list[PgAuditEntry] = []
    for line in content.splitlines():
        entry = parse_pgaudit_line(line)
        if entry is not None:
            entries.append(entry)
    return entries


def reconcile_pgaudit(
    conn: psycopg.Connection,
    entries: list[PgAuditEntry],
) -> ReconciliationReport:
    """Rapproche les écritures pgAudit avec les événements journalisés dans deedbook."""
    report = ReconciliationReport(total_entries=len(entries))

    for entry in entries:
        is_write = entry.audit_class in _WRITE_CLASSES or entry.command in _WRITE_COMMANDS
        if not is_write:
            continue

        report.writes_analyzed += 1

        if not entry.correlation_id:
            report.orphans.append(
                OrphanWrite(
                    entry=entry,
                    reason="Aucun correlation_id dans la requête SQL",
                )
            )
            continue

        row = conn.execute(
            """
            SELECT event_id, resource_name
            FROM deedbook.audit_events
            WHERE correlation_id = %s
            LIMIT 1
            """,
            (entry.correlation_id,),
        ).fetchone()

        if row is None:
            report.orphans.append(
                OrphanWrite(
                    entry=entry,
                    reason=f"correlation_id '{entry.correlation_id}' introuvable dans audit_events",
                )
            )
        else:
            report.matched_events += 1

    return report
