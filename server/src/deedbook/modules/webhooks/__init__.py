"""Module webhooks deedbook : notifications HTTP POST sur événements critiques."""

from __future__ import annotations

from deedbook.modules.webhooks.notifier import dispatch_webhook, is_critical_event
from deedbook.modules.webhooks.routes import router

__all__ = ["dispatch_webhook", "is_critical_event", "router"]
