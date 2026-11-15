import datetime as dt
import uuid

import pytest
from pydantic import ValidationError

from deedbook.api.schemas import AuditEvent, Change, Result


def make_valid_event(**overrides) -> dict:
    base = {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid4()),
        "idempotency_key": "req_8f3a2c1d-1234",
        "occurred_at": dt.datetime.now(dt.UTC).isoformat(),
        "actor": {"type": "human", "end_user": "u1", "role": "admin"},
        "service_account": None,
        "origin": {"app": "testapp", "component": "api"},
        "action": "create",
        "resource": {"type": "record", "name": "users", "id": "42"},
        "result": {"status": "success"},
        "change": {"before": None, "after": {"name": "Alice"}},
    }
    base.update(overrides)
    return base


def test_valid_event_parses():
    data = make_valid_event()
    ev = AuditEvent.model_validate(data)
    assert ev.schema_version == "1.0"
    assert ev.action == "create"
    assert ev.change.after == {"name": "Alice"}


def test_unknown_field_rejected():
    data = make_valid_event(unknown_field="bad")
    with pytest.raises(ValidationError) as exc:
        AuditEvent.model_validate(data)
    assert "extra_forbidden" in str(exc.value)


def test_clock_skew_future_rejected():
    future = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10)
    data = make_valid_event(occurred_at=future.isoformat())
    with pytest.raises(ValidationError) as exc:
        AuditEvent.model_validate(data)
    assert "dans le futur" in str(exc.value)


def test_service_actor_requires_service_account():
    data = make_valid_event(
        actor={"type": "service", "end_user": None},
        service_account=None,
    )
    with pytest.raises(ValidationError) as exc:
        AuditEvent.model_validate(data)
    assert "service_account requis" in str(exc.value)


def test_action_rules_for_changes():
    # create on record requires after, forbids before
    data = make_valid_event(action="create", change={"before": {"a": 1}, "after": {"b": 2}})
    with pytest.raises(ValidationError) as exc:
        AuditEvent.model_validate(data)
    assert "change.before est interdit" in str(exc.value)

    # update on record requires both
    data = make_valid_event(action="update", change={"before": None, "after": {"b": 2}})
    with pytest.raises(ValidationError) as exc:
        AuditEvent.model_validate(data)
    assert "change.before et change.after sont obligatoires" in str(exc.value)

    # delete on record requires before, forbids after
    data = make_valid_event(action="delete", change={"before": {"a": 1}, "after": {"b": 2}})
    with pytest.raises(ValidationError) as exc:
        AuditEvent.model_validate(data)
    assert "change.after est interdit" in str(exc.value)

    # read forbids change
    data = make_valid_event(action="read", change={"before": {"a": 1}})
    with pytest.raises(ValidationError) as exc:
        AuditEvent.model_validate(data)
    assert "change interdit" in str(exc.value)


def test_change_depth_limit():
    nested = {"l1": {"l2": {"l3": {"l4": {"l5": "trop_profond"}}}}}
    with pytest.raises(ValidationError) as exc:
        Change.model_validate({"after": nested})
    assert "profondeur" in str(exc.value)


def test_change_size_limit():
    huge = {"payload": "x" * 9000}
    with pytest.raises(ValidationError) as exc:
        Change.model_validate({"after": huge})
    assert "taille maximale" in str(exc.value)


def test_result_message_truncated():
    res = Result.model_validate({"status": "error", "message": "a" * 600})
    assert len(res.message) == 500
