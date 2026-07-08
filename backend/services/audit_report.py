"""iter55.17 — Monthly audit report helpers.

Aggregates a set of audit_log entries into executive-summary KPIs, computes
an integrity hash of the dataset (so the printed PDF is tamper-evident), and
exposes ISO month-range boundaries used by the monthly export endpoints.

Pure functions — no DB access. The router is responsible for fetching the
raw entries (via services.transactions.fetch_audit_entries) and then feeding
them here.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


# Human labels for the action-family groups we surface in the executive
# summary. Anything not in this map falls into "Otros".
ACTION_GROUP_LABELS: Dict[str, str] = {
    "order": "Órdenes",
    "rate": "Tasas",
    "user": "Usuarios",
    "settings": "Configuración",
    "kyc": "KYC",
    "appeal": "Apelaciones",
    "withdrawal": "Retiros VIP",
    "company_fund": "Fondo empresa",
    "company_adjustment": "Aportes / Salidas capital",
    "product": "Productos",
    "currency": "Monedas",
    "blocklist": "Bloqueos",
    "vip": "Conversiones VIP",
}


# ============================================================
# Date helpers
# ============================================================

def month_range_iso(year: int, month: int) -> Tuple[str, str]:
    """Return the (since, until) ISO strings that cover the entire calendar
    month. `since` is the first microsecond of day 1, `until` is the last
    microsecond of the last day. Both are UTC and safe to use with the
    existing string-compare filter on `audit_log.created_at`.
    """
    from datetime import timedelta
    if month < 1 or month > 12 or year < 2020 or year > 2100:
        raise ValueError(f"año/mes inválido: {year}/{month}")
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        first_next = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        first_next = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    end = first_next - timedelta(microseconds=1)
    return (start.isoformat(), end.isoformat())


def month_label(year: int, month: int) -> str:
    """Human-readable Spanish month label used in the PDF header and the
    email subject. Example: 'Enero 2026'."""
    names = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]
    return f"{names[month - 1]} {year}"


# ============================================================
# KPI aggregation
# ============================================================

def _group_of(action: str) -> str:
    """Coarse family for the 'actions by group' KPI. Uses the token before
    the first dot in the action code (e.g. 'order.approved' → 'order')."""
    if not action:
        return "otros"
    head = action.split(".", 1)[0]
    return head


def _label_for_group(group: str) -> str:
    return ACTION_GROUP_LABELS.get(group, group.replace("_", " ").capitalize() or "Otros")


def _permission_bucket(entry: dict) -> str:
    """Classify a row by the actor's effective permission scope at the
    moment of the action. Values: 'admin' · 'staff_default' · 'scoped'.
    Old rows (pre iter55.16b) count as 'legacy'."""
    eff = entry.get("actor_permissions_effective")
    if eff == "all":
        return "admin"
    if eff == "all_staff_default":
        return "staff_default"
    if isinstance(eff, list):
        return "scoped" if eff else "staff_default"
    return "legacy"


# Actions we flag as anti-fraud signals in the exec summary.
ANTI_FRAUD_ACTIONS: set[str] = {
    "user.reject_phone",
    "user.verify_phone",
    "blocklist.add",
    "blocklist.bulk_import",
    "user.role_change",
    "user.balance_edit",
}


def compute_monthly_kpis(entries: List[dict]) -> Dict[str, Any]:
    """Aggregate a month's worth of audit entries into the KPIs the PDF's
    executive summary renders. Never raises — bad rows are skipped."""
    total = len(entries)

    # 1. Actions by group (top 10, DESC)
    groups: Counter = Counter()
    for e in entries:
        groups[_group_of(e.get("action", ""))] += 1
    by_group = [
        {"code": g, "label": _label_for_group(g), "count": c}
        for g, c in groups.most_common(10)
    ]

    # 2. Top actors (top 5)
    actor_counter: Counter = Counter()
    actor_meta: Dict[str, Dict[str, str]] = {}
    for e in entries:
        aid = e.get("actor_id", "") or "-"
        actor_counter[aid] += 1
        if aid not in actor_meta:
            actor_meta[aid] = {
                "name": e.get("actor_name") or e.get("actor_email") or aid,
                "email": e.get("actor_email", ""),
                "role": e.get("actor_role", ""),
            }
    top_actors = [
        {
            "actor_id": aid,
            "name": actor_meta[aid]["name"],
            "email": actor_meta[aid]["email"],
            "role": actor_meta[aid]["role"],
            "count": c,
        }
        for aid, c in actor_counter.most_common(5)
    ]

    # 3. Anti-fraud signals
    anti_fraud: Counter = Counter()
    for e in entries:
        action = e.get("action", "")
        if action in ANTI_FRAUD_ACTIONS:
            anti_fraud[action] += 1
    anti_fraud_list = [
        {"action": k, "count": v}
        for k, v in sorted(anti_fraud.items(), key=lambda kv: kv[1], reverse=True)
    ]

    # 4. Permission-scope distribution
    perm_bucket: Counter = Counter()
    for e in entries:
        perm_bucket[_permission_bucket(e)] += 1

    return {
        "total_actions": total,
        "by_group": by_group,
        "top_actors": top_actors,
        "anti_fraud": anti_fraud_list,
        "permission_scope": dict(perm_bucket),
        # Distinct actor count is handy for "quantas manos tocaron el sistema"
        "distinct_actors": len(actor_counter),
    }


# ============================================================
# Integrity hash
# ============================================================

def compute_integrity_hash(entries: List[dict], period_label: str) -> str:
    """SHA-256 of the ordered canonical projection of the entries. Any
    downstream tampering with the audit rows (edit, insert, delete) changes
    this digest, so an operator can verify the printed PDF still matches
    what's currently in Mongo by re-running the export.

    Canonical projection keeps only the fields that identify the action —
    NOT free-form summaries that might diverge across environments.
    """
    canonical = [
        {
            "id": e.get("id", ""),
            "at": e.get("created_at", ""),
            "actor": e.get("actor_id", ""),
            "action": e.get("action", ""),
            "entity": f"{e.get('entity_type', '')}:{e.get('entity_id', '')}",
        }
        for e in sorted(entries, key=lambda x: x.get("created_at", ""))
    ]
    payload = json.dumps(
        {"period": period_label, "count": len(entries), "rows": canonical},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
