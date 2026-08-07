"""iter167 — BankReconciliationMatchingEngine (spec §10-§15, §44-§47, §58-§63).

Deterministic scoring per the official spec point table (§11):
  amount  : exact +45 · within tolerance +30 · else 0
  currency: equal +10 · different → candidate DISCARDED (pre-filter)
  name    : exact +25 · ≥95% +23 · 90-94% +20 · 80-89% +15 · 70-79% +8 · <70% 0
  date    : same +10 · 1d +8 · 2d +5 · 3d +2 · else 0
  ref     : exact +20 · partial +10
  method  : expected == detected +5
  account : MUST match when both sides known → else DISCARD (hard gate)

Decision (§12-§14, §44): auto ≥ auto_match_score (default 95) AND exact
amount AND winner separation ≥ minimum_score_difference AND amount ≤
max_auto_confirmation_amount AND account determinable AND order pending.
80-94.99 → manual review · <80 → unmatched. False positives are the enemy
(§62): any ambiguity → manual review.
"""
import logging
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from db_client import db

logger = logging.getLogger(__name__)

ALGORITHM_VERSION = "RECON_V1.0"

DEFAULT_CONFIG: Dict[str, Any] = {
    "auto_match_enabled": True,
    "auto_match_score": 95,
    "manual_review_score": 80,
    "minimum_score_difference": 10,
    "date_window_days": 14,
    "amount_tolerance_pct": 0.5,
    "max_auto_confirmation_amount": 10000,
    "require_exact_amount": True,
    "enable_ocr": True,
}

_CONFIG_RANGES = {
    "auto_match_score": (0, 100),
    "manual_review_score": (0, 100),
    "minimum_score_difference": (0, 100),
    "date_window_days": (1, 365),
    "amount_tolerance_pct": (0, 20),
    "max_auto_confirmation_amount": (0, 100000000),
}

_BANK_NOISE = {"llc", "inc", "sa", "sl", "co", "ltd", "de", "del", "la", "el",
               "los", "las", "y", "and", "mr", "mrs", "sr", "sra"}


async def get_config() -> Dict[str, Any]:
    doc = await db.settings.find_one({"id": "reconciliation_config"}, {"_id": 0, "id": 0})
    cfg = dict(DEFAULT_CONFIG)
    if doc:
        for k in DEFAULT_CONFIG:
            if k in doc:
                cfg[k] = doc[k]
    return cfg


def validate_config_value(key: str, value: Any) -> Any:
    if key == "auto_match_enabled" or key == "require_exact_amount" or key == "enable_ocr":
        return bool(value)
    v = float(value)
    lo, hi = _CONFIG_RANGES.get(key, (0, 100))
    if v < lo or v > hi:
        raise ValueError(f"{key} debe estar entre {lo} y {hi}")
    return v


def normalize_name(name: Any) -> str:
    """§9/§59 — uppercase, strip accents/punctuation, collapse spaces."""
    s = str(name or "").upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return " ".join(s.split())


def name_similarity(a: Any, b: Any) -> float:
    """§60 — MAX(sequence ratio, token sort, token set)."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    base = SequenceMatcher(None, na, nb).ratio()
    ta = [t for t in na.split() if t not in _BANK_NOISE] or na.split()
    tb = [t for t in nb.split() if t not in _BANK_NOISE] or nb.split()
    token_sort = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    sa, sb = set(ta), set(tb)
    token_set = len(sa & sb) / min(len(sa), len(sb)) if sa and sb else 0.0
    return max(base, token_sort, token_set)


def _name_points(sim: float, exact: bool) -> int:
    if exact:
        return 25
    if sim >= 0.95:
        return 23
    if sim >= 0.90:
        return 20
    if sim >= 0.80:
        return 15
    if sim >= 0.70:
        return 8
    return 0


def _iso_date(s: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def score_pair(tx: Dict, order: Dict, cfg: Dict) -> Dict[str, Any]:
    """§11 + §24 — returns the explainable breakdown."""
    amount = float(tx.get("amount") or 0)
    expected = float(order.get("amount_from") or 0)
    diff = abs(amount - expected)
    tol = max(0.01, expected * float(cfg["amount_tolerance_pct"]) / 100.0)
    amount_exact = diff < 0.005
    amount_within_tol = diff <= tol
    amount_score = 45 if amount_exact else (30 if amount_within_tol else 0)

    tx_name = tx.get("sender_name") or ""
    best_sim, exact_name = 0.0, False
    for cand_name in (order.get("sender_name"), order.get("user_name")):
        if not cand_name:
            continue
        sim = name_similarity(tx_name, cand_name)
        if normalize_name(tx_name) and normalize_name(tx_name) == normalize_name(cand_name):
            exact_name = True
        best_sim = max(best_sim, sim)
    if not tx_name and tx.get("description"):
        best_sim = max(best_sim,
                       name_similarity(tx.get("description"), order.get("sender_name")),
                       name_similarity(tx.get("description"), order.get("user_name")))
    name_score = _name_points(best_sim, exact_name)

    tx_date, order_date = _iso_date(tx.get("transaction_date")), _iso_date(order.get("created_at"))
    date_diff = abs((tx_date - order_date).days) if (tx_date and order_date) else None
    date_score = 0
    if date_diff is not None:
        date_score = {0: 10, 1: 8, 2: 5, 3: 2}.get(date_diff, 0)

    haystack = normalize_name(" ".join(filter(None, [
        tx.get("reference") or "", tx.get("description") or "",
        tx.get("transaction_id_bank") or "", tx.get("confirmation_number") or ""])))
    oid = normalize_name(order.get("id") or "")
    ref_score = 0
    if oid and oid.replace(" ", "") and oid.replace(" ", "") in haystack.replace(" ", ""):
        ref_score = 20
    elif oid[:8] and oid[:8].replace(" ", "") in haystack.replace(" ", ""):
        ref_score = 10
    email = normalize_name(order.get("user_email") or "")
    if ref_score == 0 and email and email.replace(" ", "") in haystack.replace(" ", ""):
        ref_score = 10

    method_score = 0
    detected = normalize_name(tx.get("payment_method") or "")
    account_label = normalize_name(order.get("payment_account_label") or "")
    if detected and detected != "OTROS" and detected in account_label:
        method_score = 5

    breakdown = {
        "amount_score": amount_score,
        "currency_score": 10,  # candidates are pre-filtered to same currency
        "name_score": name_score,
        "date_score": date_score,
        "reference_score": ref_score,
        "payment_method_score": method_score,
        "name_similarity": round(best_sim, 4),
        "date_difference_days": date_diff,
    }
    total = amount_score + 10 + name_score + date_score + ref_score + method_score
    breakdown["total"] = total
    return {"score": total, "breakdown": breakdown,
            "amount_exact": amount_exact, "amount_within_tolerance": amount_within_tol,
            "amount_delta": round(amount - expected, 2)}


async def load_pending_orders(currency: str) -> List[Dict]:
    """§15 — only payment-pending states are candidates."""
    return await db.orders.find(
        {"status": {"$in": ["pending", "requires_double_approval"]},
         "from_code": currency.upper()},
        {"_id": 0, "id": 1, "user_id": 1, "user_name": 1, "user_email": 1,
         "sender_name": 1, "amount_from": 1, "amount_to": 1, "from_code": 1,
         "to_code": 1, "created_at": 1, "status": 1, "payment_account_id": 1,
         "payment_account_label": 1},
    ).sort("created_at", -1).to_list(5000)


def rank_candidates(tx: Dict, orders: List[Dict], cfg: Dict,
                    import_bank_account_id: str, taken: set) -> List[Dict]:
    """Phase 1 filters (§34-35): currency pre-filtered, hard account gate,
    date window. Phase 2: full scoring."""
    tx_date = _iso_date(tx.get("transaction_date"))
    window = int(cfg["date_window_days"])
    ranked = []
    for o in orders:
        if o["id"] in taken:
            continue
        # §11 hard gate: receiving account must match when both sides known.
        if (import_bank_account_id and o.get("payment_account_id")
                and o["payment_account_id"] != import_bank_account_id):
            continue
        o_date = _iso_date(o.get("created_at"))
        if tx_date and o_date:
            delta = (tx_date - o_date).days
            if delta < -1 or delta > window:
                continue
        s = score_pair(tx, o, cfg)
        if s["score"] >= 40:  # keep the list small but informative
            ranked.append({
                "order_id": o["id"], "score": s["score"],
                "breakdown": s["breakdown"],
                "amount_exact": s["amount_exact"],
                "amount_within_tolerance": s["amount_within_tolerance"],
                "amount_delta": s["amount_delta"],
                "order_status": o.get("status"),
                "order_amount": o.get("amount_from"),
                "order_user_name": o.get("user_name"),
                "order_sender_name": o.get("sender_name"),
                "order_created_at": o.get("created_at"),
                "payment_account_id": o.get("payment_account_id"),
                "payment_account_label": o.get("payment_account_label"),
            })
    ranked.sort(key=lambda c: -c["score"])
    return ranked[:5]


def decide(tx: Dict, candidates: List[Dict], cfg: Dict,
           import_bank_account_id: str) -> Dict[str, Any]:
    """§12-§14, §44-§47, §62. Returns {decision, flag}."""
    if not candidates:
        return {"decision": "unmatched", "flag": None}
    best = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None

    flag = None
    if not best["amount_exact"]:
        delta = best.get("amount_delta") or 0
        flag = "possible_overpayment" if delta > 0 else "possible_partial_payment"

    if best["score"] < cfg["manual_review_score"]:
        return {"decision": "unmatched", "flag": flag}

    auto_blockers = [
        not cfg["auto_match_enabled"],
        best["score"] < cfg["auto_match_score"],
        cfg["require_exact_amount"] and not best["amount_exact"],
        not best["amount_exact"] and flag is not None,  # §46-47 never auto
        second is not None and (best["score"] - second["score"]) < cfg["minimum_score_difference"],
        float(cfg["max_auto_confirmation_amount"] or 0) > 0
        and float(tx.get("amount") or 0) > float(cfg["max_auto_confirmation_amount"]),
        best.get("order_status") != "pending",
        # §13: receiving account must be determinable for auto.
        not (import_bank_account_id and best.get("payment_account_id")
             and best["payment_account_id"] == import_bank_account_id),
        # §45: same amount + similar name on 2+ orders without reference.
        second is not None and second["amount_exact"] and best["amount_exact"]
        and best["breakdown"]["reference_score"] == 0
        and abs(best["breakdown"]["name_score"] - second["breakdown"]["name_score"]) <= 5,
    ]
    if any(auto_blockers):
        return {"decision": "review", "flag": flag}
    return {"decision": "auto", "flag": flag}


async def recon_audit(action: str, actor: Dict, tx: Optional[Dict] = None,
                      order_id: Optional[str] = None, prev_status: Optional[str] = None,
                      new_status: Optional[str] = None, score: Optional[float] = None,
                      details: Optional[Dict] = None, import_id: Optional[str] = None,
                      ip: Optional[str] = None) -> None:
    """§23 — dedicated reconciliation_audit_log (never deleted)."""
    import uuid
    from auth_utils import iso, now_utc
    try:
        await db.reconciliation_audit_log.insert_one({
            "id": f"raud_{uuid.uuid4().hex[:12]}",
            "bank_transaction_id": tx["id"] if tx else None,
            "order_id": order_id,
            "action": action,
            "previous_status": prev_status,
            "new_status": new_status,
            "confidence_score": score,
            "algorithm_version": ALGORITHM_VERSION,
            "matching_details": details or {},
            "performed_by": actor.get("user_id"),
            "performed_by_name": actor.get("name") or actor.get("email"),
            "performed_at": iso(now_utc()),
            "ip_address": ip,
            "statement_import_id": import_id or (tx or {}).get("statement_import_id"),
        })
    except Exception as e:
        logger.error(f"recon audit write failed: {e}")


SYSTEM_ACTOR = {"user_id": "system_reconciliation", "role": "admin",
                "name": "Conciliación automática", "email": "system@resilience"}


async def approve_order_from_reconciliation(order: Dict, tx: Dict, actor: Dict,
                                            auto: bool) -> Dict:
    """§18-§19 — atomic pending→approved with reconciliation stamps.
    The filtered update IS the idempotency lock (Mongo doc-level atomicity)."""
    from auth_utils import iso, now_utc
    from services.orders_helpers import run_post_status_side_effects
    from audit_log import log_action

    prev_status = order["status"]
    note = (f"Conciliación bancaria {'automática' if auto else 'manual'} — "
            f"movimiento {tx['id']} ({tx.get('transaction_date')}, "
            f"{tx.get('amount')} {tx.get('currency')})")
    res = await db.orders.update_one(
        {"id": order["id"], "status": "pending",
         "reconciliation.bank_transaction_id": {"$exists": False}},
        {"$set": {
            "status": "approved", "admin_note": note,
            "updated_at": iso(now_utc()),
            "payment_confirmed_at": iso(now_utc()),
            "payment_confirmation_source": "BANK_RECONCILIATION",
            "bank_transaction_id": tx["id"],
            "reconciliation_score": tx.get("confidence_score"),
            "reconciliation": {
                "bank_transaction_id": tx["id"],
                "statement_import_id": tx.get("statement_import_id"),
                "matched_at": iso(now_utc()),
                "auto": auto,
                "confidence_score": tx.get("confidence_score"),
                "algorithm_version": ALGORITHM_VERSION,
            },
        }},
    )
    if res.modified_count != 1:
        raise RuntimeError("order_no_longer_pending")
    updated = await db.orders.find_one({"id": order["id"]}, {"_id": 0})
    try:
        await run_post_status_side_effects(updated, "approved", prev_status)
    except Exception as e:
        logger.error(f"reconciliation side effects failed for {order['id']}: {e}")
    try:
        from routes.admin import _publish_order_status_sse
        await _publish_order_status_sse(order["id"], updated, "approved", prev_status)
    except Exception as e:
        logger.error(f"reconciliation SSE failed: {e}")
    try:
        await log_action(
            db, actor, "order.reconciled", "order", order["id"],
            summary=(f"Orden conciliada {'automáticamente' if auto else 'manualmente'} "
                     f"con movimiento bancario {tx['id']}"),
            details={"bank_transaction_id": tx["id"], "auto": auto,
                     "score": tx.get("confidence_score"),
                     "amount": tx.get("amount"), "currency": tx.get("currency"),
                     "prev": prev_status, "new": "approved"},
        )
    except Exception as e:
        logger.error(f"reconciliation audit failed: {e}")
    return updated


async def run_matching(import_doc: Dict, tx_docs: List[Dict]) -> Dict[str, int]:
    """Matches freshly-imported CREDIT transactions. Mutates tx docs in DB."""
    from auth_utils import iso, now_utc
    cfg = await get_config()
    orders = await load_pending_orders(import_doc["currency"])
    bank_account_id = import_doc.get("bank_account_id") or ""
    taken: set = set()
    counts = {"auto": 0, "review": 0, "unmatched": 0}

    for tx in tx_docs:
        if tx.get("direction") != "credit" or tx.get("status") in ("duplicate", "error"):
            continue
        candidates = rank_candidates(tx, orders, cfg, bank_account_id, taken)
        verdict = decide(tx, candidates, cfg, bank_account_id)
        best = candidates[0] if candidates else None
        update = {
            "candidates": candidates,
            "confidence_score": best["score"] if best else 0,
            "review_flag": verdict["flag"],
            "algorithm_version": ALGORITHM_VERSION,
            "updated_at": iso(now_utc()),
        }
        if verdict["decision"] == "auto":
            order = next((o for o in orders if o["id"] == best["order_id"]), None)
            try:
                tx["confidence_score"] = best["score"]
                await approve_order_from_reconciliation(order, tx, SYSTEM_ACTOR, auto=True)
                update.update({"status": "auto_matched",
                               "matched_order_id": best["order_id"],
                               "match_details": best,
                               "matched_at": iso(now_utc()),
                               "matched_by": "system_reconciliation",
                               "reviewed_by": "system_reconciliation",
                               "reviewed_at": iso(now_utc())})
                taken.add(best["order_id"])
                counts["auto"] += 1
                await recon_audit("AUTO_MATCHED", SYSTEM_ACTOR, tx=tx,
                                  order_id=best["order_id"],
                                  prev_status="unprocessed", new_status="auto_matched",
                                  score=best["score"], details=best["breakdown"])
            except RuntimeError:
                update["status"] = "manual_review"
                counts["review"] += 1
        elif verdict["decision"] == "review":
            update["status"] = "manual_review"
            counts["review"] += 1
            if best:
                await recon_audit("MATCH_SUGGESTED", SYSTEM_ACTOR, tx=tx,
                                  order_id=best["order_id"],
                                  new_status="manual_review",
                                  score=best["score"], details=best["breakdown"])
        else:
            update["status"] = "unmatched"
            counts["unmatched"] += 1
        await db.bank_transactions.update_one({"id": tx["id"]}, {"$set": update})
    return counts
