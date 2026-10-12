"""Role-based permissions: the single place that says which role may do what.

Roles:

* ``admin`` - everything, including user management, model governance and the audit log.
* ``analyst`` - day-to-day detection work: imports, scoring, alert and incident handling,
  drift analyses and data exports.
* ``viewer`` - read-only visibility (for example a manager or an auditor): sees dashboards,
  alerts, incidents, models and drift results, but cannot change anything or export data.

Every API route declares exactly one permission (``api.deps.allow``), and a regression test
fails if a route is added without one. The web UI reads the caller's permissions from
``/api/auth/me`` to hide controls, but the server is always the enforcing side.
"""

from __future__ import annotations

ROLES = ("admin", "analyst", "viewer")

_ALL = frozenset(ROLES)
_WORK = frozenset({"admin", "analyst"})
_ADMIN = frozenset({"admin"})

PERMISSIONS: dict[str, frozenset[str]] = {
    # reading
    "dashboard.read": _ALL,
    "data.read": _ALL,  # imports, events, scoring runs, traffic replay
    "alerts.read": _ALL,
    "incidents.read": _ALL,
    "models.read": _ALL,
    "drift.read": _ALL,
    "users.read": _ALL,  # names for assignees and history
    "config.read": _ALL,  # schemas, severity rules, drift defaults, governance protocol
    # detection work
    "data.import": _WORK,
    "scoring.run": _WORK,
    "alerts.write": _WORK,
    "incidents.write": _WORK,
    "drift.write": _WORK,
    "data.export": _WORK,  # CSV / Markdown exports leave the system
    # administration
    "models.manage": _ADMIN,  # register, evaluate, approve, reject, activate, verify
    "users.manage": _ADMIN,
    "audit.read": _ADMIN,
}


def allowed(role: str, permission: str) -> bool:
    if permission not in PERMISSIONS:
        raise KeyError(f"unknown permission {permission!r}")
    return role in PERMISSIONS[permission]


def permissions_for(role: str) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)
