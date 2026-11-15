"""Moteur de masquage des champs sensibles (spec §3 : redact, hash HMAC salé, mask)."""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
from typing import Any


def mask_string(
    val: str,
    strategy: str,
    hmac_key: bytes | None = None,
    salt: str = "",
    keep: int = 4,
) -> str:
    """Applique une stratégie de masquage sur une chaîne."""
    if strategy == "redact":
        return "[redacted]"
    if strategy == "hash":
        if not hmac_key:
            return hashlib.sha256(f"{salt}:{val}".encode()).hexdigest()[:16]
        return hmac.new(hmac_key, f"{salt}:{val}".encode(), hashlib.sha256).hexdigest()[:16]
    if strategy == "mask":
        if len(val) <= keep:
            return val
        return val[:keep] + "*" * (len(val) - keep)
    return val


def _matches(pattern: str, text: str) -> bool:
    """Correspondance insensible à la casse avec motif glob."""
    return fnmatch.fnmatch(text.lower(), pattern.lower())


def mask_dict(
    data: dict[str, Any],
    rules: list[dict[str, Any]],
    resource_name: str | None = None,
    hmac_key: bytes | None = None,
    salt: str = "",
    depth: int = 1,
) -> dict[str, Any]:
    """Applique récursivement les règles de masquage sur un dictionnaire (before/after)."""
    if depth > 4 or not isinstance(data, dict):
        return data

    res = resource_name or ""
    masked: dict[str, Any] = {}

    for k, v in data.items():
        matched_rule = None
        for rule in rules:
            r_pat = rule.get("resource", "*")
            f_pat = rule.get("field", "*")
            if (r_pat == "*" or _matches(r_pat, res)) and _matches(f_pat, k):
                matched_rule = rule
                break

        if matched_rule is not None:
            strat = matched_rule.get("strategy", "redact")
            keep = int(matched_rule.get("keep", 4))
            if isinstance(v, str):
                masked[k] = mask_string(v, strat, hmac_key=hmac_key, salt=salt, keep=keep)
            elif v is None:
                masked[k] = None
            else:
                masked[k] = mask_string(str(v), strat, hmac_key=hmac_key, salt=salt, keep=keep)
        elif isinstance(v, dict):
            masked[k] = mask_dict(
                v,
                rules,
                resource_name=resource_name,
                hmac_key=hmac_key,
                salt=salt,
                depth=depth + 1,
            )
        elif isinstance(v, list):
            masked[k] = [
                mask_dict(
                    item,
                    rules,
                    resource_name=resource_name,
                    hmac_key=hmac_key,
                    salt=salt,
                    depth=depth + 1,
                )
                if isinstance(item, dict)
                else item
                for item in v
            ]
        else:
            masked[k] = v

    return masked
