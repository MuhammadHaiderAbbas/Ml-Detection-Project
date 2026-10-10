"""Configurable, documented severity (triage priority) rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

SEVERITIES = ("low", "medium", "high", "critical")


class SeverityRuleError(ValueError):
    pass


@dataclass(frozen=True)
class SeverityRules:
    version: str
    description: str
    rules: tuple[dict[str, Any], ...]
    default: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "SeverityRules":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SeverityRules":
        try:
            rules = tuple(d["rules"])
            default = d["default"]
            version = str(d["version"])
        except KeyError as exc:
            raise SeverityRuleError(f"severity rules missing {exc}") from exc
        ids = set()
        for r in (*rules, default):
            if r.get("severity") not in SEVERITIES:
                raise SeverityRuleError(f"rule {r.get('rule_id')!r}: severity must be one of {SEVERITIES}")
            if not r.get("rule_id") or r["rule_id"] in ids:
                raise SeverityRuleError("every rule needs a unique rule_id")
            ids.add(r["rule_id"])
            if "min_score" in r and not 0 <= float(r["min_score"]) <= 1:
                raise SeverityRuleError(f"rule {r['rule_id']!r}: min_score must be within [0, 1]")
        for r in rules:
            if not isinstance(r.get("classes"), list) or not r["classes"]:
                raise SeverityRuleError(f"rule {r['rule_id']!r}: classes must be a non-empty list of patterns")
        return cls(version=version, description=d.get("description", ""), rules=rules, default=default)

    def evaluate(self, predicted_class: str, score: float | None) -> tuple[str, str]:
        """Return (severity, rule_id) for a suspicious prediction."""
        for r in self.rules:
            if not any(fnmatchcase(predicted_class, p) for p in r["classes"]):
                continue
            if "min_score" in r and (score is None or score < float(r["min_score"])):
                continue
            return r["severity"], r["rule_id"]
        return self.default["severity"], self.default["rule_id"]

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "description": self.description,
                "rules": list(self.rules), "default": self.default}
