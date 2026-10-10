"""Audit logging for sensitive actions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..db.models import AuditLog, User


def record(
    db: Session,
    action: str,
    *,
    actor: User | None = None,
    actor_name: str | None = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    details: dict[str, Any] | None = None,
    client_ip: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        action=action,
        actor_id=actor.id if actor else None,
        actor_name=actor.username if actor else actor_name,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        details=details or {},
        client_ip=client_ip,
    )
    db.add(entry)
    return entry
