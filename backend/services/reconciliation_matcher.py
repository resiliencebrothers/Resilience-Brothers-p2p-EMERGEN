"""iter167 — BankReconciliationMatchingEngine (spec §10-§15, §44-§47, §58-§63).

Deterministic scoring — RECON_V2.0 (iter177: los VIP no controlan el concepto
bancario, así que referencia/método salen del total):
  amount  : exact +55 · within tolerance +35 · else 0
  currency: equal +10 · different → candidate DISCARDED (pre-filter)
  name    : exact +30 · ≥95% +27 · 90-94% +23 · 80-89% +17 · 70-79% +9 · <70% 0
  surname : OBLIGATORIO para auto (spec V2 apellidos): similitud ≥ umbral
            configurable (surname_match_threshold, def. 0.75) o el movimiento
            va a revisión con surname_mismatch. Coincide → +5.
  initials: JOSE M PEREZ GARCIA ≡ JOSE MANUEL PEREZ GARCIA
  date    : same +10 · 1d +8 · 2d +5 · 3d +2 · else 0
  ref     : RB-XXXXXX en concepto → SOLO desempate (no suma al total)
  account : optional hard gate (require_account_match)

Decision (§12-§14, §44): auto ≥ auto_match_score (default 95) AND exact
amount AND winner separation ≥ minimum_score_difference AND amount ≤
max_auto_confirmation_amount AND account determinable AND order pending.
80-94.99 → manual review · <80 → unmatched. False positives are the enemy
(§62): any ambiguity → manual review.
"""
import logging
import re
import unicodedata
import uuid
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from db_client import db
from auth_utils import iso, now_utc
from audit_log import log_action
from services.order_events import publish_order_status_sse
from services.vip_batch_ops import (
    apply_item_decision, notify_vip_item_decision, refresh_batch_totals,
)

logger = logging.getLogger(__name__)

ALGORITHM_VERSION = "RECON_V2.0"

DEFAULT_CONFIG: Dict[str, Any] = {
    "auto_match_enabled": True,
    # iter177 V2 — 90 alcanzable con monto exacto (55) + moneda (10) +
    # nombre exacto (30) = 95, sin depender de referencia bancaria.
    "auto_match_score": 90,
    "manual_review_score": 80,
    "minimum_score_difference": 10,
    "date_window_days": 14,
    "amount_tolerance_pct": 0.5,
    "max_auto_confirmation_amount": 10000,
    "require_exact_amount": True,
    # iter175 — OFF por defecto: los extractos reales (fotos → PDF) no
    # siempre permiten determinar la cuenta de cobro; con nombre exacto +
    # monto exacto + fecha el match ya es sólido. Activable en Reglas.
    "require_account_match": False,
    # Spec V2 apellidos — apellido OBLIGATORIO para auto: similitud mínima
    # (0.75 acepta typos OCR tipo GONZALEZ↔GONSALES; 0 desactiva el gate).
    "surname_match_threshold": 0.75,
    "enable_ocr": True,
}

_CONFIG_RANGES = {
    "auto_match_score": (0, 100),
    "manual_review_score": (0, 100),
    "minimum_score_difference": (0, 100),
    "date_window_days": (1, 365),
    "amount_tolerance_pct": (0, 20),
    "max_auto_confirmation_amount": (0, 100000000),
    "surname_match_threshold": (0, 1),
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


_BOOL_CONFIG_KEYS = {"auto_match_enabled", "require_exact_amount",
                     "require_account_match", "enable_ocr"}


def validate_config_value(key: str, value: Any) -> Any:
    if key in _BOOL_CONFIG_KEYS:
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


def _tokens_match(a: str, b: str) -> bool:
    """Iniciales (spec V2): 'M' ≡ 'MANUEL'."""
    if a == b:
        return True
    return (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b))


def _token_set_similarity(ta: list, tb: list) -> float:
    sa, sb = set(ta), set(tb)
    if not sa or not sb:
        return 0.0
    small, big = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return sum(1 for x in small
               if any(_tokens_match(x, y) for y in big)) / len(small)


def name_similarity(a: Any, b: Any) -> float:
    """§60 — MAX(sequence ratio, token sort, token set con iniciales)."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    base = SequenceMatcher(None, na, nb).ratio()
    ta = [t for t in na.split() if t not in _BANK_NOISE] or na.split()
    tb = [t for t in nb.split() if t not in _BANK_NOISE] or nb.split()
    token_sort = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return max(base, token_sort, _token_set_similarity(ta, tb))


def _name_points(sim: float, exact: bool) -> int:
    if exact:
        return 30
    if sim >= 0.95:
        return 27
    if sim >= 0.90:
        return 23
    if sim >= 0.80:
        return 17
    if sim >= 0.70:
        return 9
    return 0


def _surname_tokens(name: Any) -> set:
    """Tokens tras el nombre de pila — apellidos probables."""
    toks = [t for t in normalize_name(name).split() if t not in _BANK_NOISE]
    return {t for t in toks[1:] if len(t) >= 2} if len(toks) >= 2 else set()


def surname_similarity(tx_name: Any, order_name: Any) -> float:
    """Spec V2 — mejor similitud entre los apellidos registrados en la orden
    y cualquier token (≥2 letras) del remitente bancario."""
    order_sn = _surname_tokens(order_name)
    tx_toks = [t for t in normalize_name(tx_name).split()
               if t not in _BANK_NOISE and len(t) >= 2]
    if not order_sn or not tx_toks:
        return 0.0
    return max(SequenceMatcher(None, sn, tok).ratio()
               for sn in order_sn for tok in tx_toks)


def _iso_date(s: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _amount_component(tx: Dict, order: Dict, cfg: Dict) -> tuple:
    """(score, exact, within_tolerance, delta) — exact +55 · tolerance +35."""
    amount = float(tx.get("amount") or 0)
    expected = float(order.get("amount_from") or 0)
    diff = abs(amount - expected)
    tol = max(0.01, expected * float(cfg["amount_tolerance_pct"]) / 100.0)
    exact = diff < 0.005
    within_tol = diff <= tol
    score = 55 if exact else (35 if within_tol else 0)
    return score, exact, within_tol, round(amount - expected, 2)


def _name_component(tx: Dict, order: Dict, cfg: Dict) -> tuple:
    """(name_score, surname_score, best_sim, surname_sim) vs sender/user name."""
    tx_name = tx.get("sender_name") or ""
    best_sim, exact_name, surname_sim = 0.0, False, 0.0
    for cand_name in (order.get("sender_name"), order.get("user_name")):
        if not cand_name:
            continue
        sim = name_similarity(tx_name, cand_name)
        if normalize_name(tx_name) and normalize_name(tx_name) == normalize_name(cand_name):
            exact_name = True
        surname_sim = max(surname_sim, surname_similarity(tx_name, cand_name))
        best_sim = max(best_sim, sim)
    if not tx_name and tx.get("description"):
        best_sim = max(best_sim,
                       name_similarity(tx.get("description"), order.get("sender_name")),
                       name_similarity(tx.get("description"), order.get("user_name")))
        surname_sim = max(
            surname_sim,
            surname_similarity(tx.get("description"), order.get("sender_name")),
            surname_similarity(tx.get("description"), order.get("user_name")))
    name_score = _name_points(best_sim, exact_name)
    surname_score = 5 if surname_sim >= float(
        cfg.get("surname_match_threshold", 0.75)) else 0
    return name_score, surname_score, best_sim, surname_sim


def _date_component(tx: Dict, order: Dict) -> tuple:
    """(score, date_difference_days) — same +10 · 1d +8 · 2d +5 · 3d +2."""
    tx_date, order_date = _iso_date(tx.get("transaction_date")), _iso_date(order.get("created_at"))
    date_diff = abs((tx_date - order_date).days) if (tx_date and order_date) else None
    if date_diff is None:
        return 0, None
    return {0: 10, 1: 8, 2: 5, 3: 2}.get(date_diff, 0), date_diff


def _order_ref_tokens(order: Dict) -> tuple:
    """(pref, oid_flat, oid_prefix, email) — normalized + space-flattened."""
    pref = normalize_name(order.get("payment_reference") or "").replace(" ", "")
    oid = normalize_name(order.get("id") or "")
    return (pref if len(pref) >= 6 else "",
            oid.replace(" ", ""),
            oid[:8].replace(" ", ""),
            normalize_name(order.get("user_email") or "").replace(" ", ""))


def _reference_score(tx: Dict, order: Dict) -> int:
    """iter173 §61 — RB-XXXXXX payment reference in the concept = exact +20.
    V2: only used as a tiebreaker, never added to the total."""
    haystack = normalize_name(" ".join(filter(None, [
        tx.get("reference") or "", tx.get("description") or "",
        tx.get("transaction_id_bank") or "", tx.get("confirmation_number") or ""])))
    hay_flat = haystack.replace(" ", "")
    if not hay_flat:
        return 0
    pref, oid_flat, oid_prefix, email = _order_ref_tokens(order)
    for token, points in ((pref, 20), (oid_flat, 20), (oid_prefix, 10), (email, 10)):
        if token and token in hay_flat:
            return points
    return 0


def score_pair(tx: Dict, order: Dict, cfg: Dict) -> Dict[str, Any]:
    """§11 + §24 — returns the explainable breakdown."""
    amount_score, amount_exact, amount_within_tol, amount_delta = \
        _amount_component(tx, order, cfg)
    name_score, surname_score, best_sim, surname_sim = _name_component(tx, order, cfg)
    date_score, date_diff = _date_component(tx, order)
    ref_score = _reference_score(tx, order)

    breakdown = {
        "amount_score": amount_score,
        "currency_score": 10,  # candidates are pre-filtered to same currency
        "name_score": name_score,
        "surname_score": surname_score,
        "surname_similarity": round(surname_sim, 4),
        "date_score": date_score,
        # V2: la referencia NO suma al total — solo desempata duplicados.
        "reference_score": ref_score,
        "name_similarity": round(best_sim, 4),
        "date_difference_days": date_diff,
    }
    total = amount_score + 10 + name_score + surname_score + date_score
    breakdown["total"] = total
    return {"score": total, "breakdown": breakdown,
            "amount_exact": amount_exact, "amount_within_tolerance": amount_within_tol,
            "amount_delta": amount_delta}


async def load_pending_orders(currency: str) -> List[Dict]:
    """§15 — only payment-pending states are candidates."""
    docs = await db.orders.find(
        {"status": {"$in": ["pending", "requires_double_approval"]},
         "from_code": currency.upper()},
        {"_id": 0, "id": 1, "user_id": 1, "user_name": 1, "user_email": 1,
         "sender_name": 1, "amount_from": 1, "amount_to": 1, "from_code": 1,
         "to_code": 1, "created_at": 1, "status": 1, "payment_account_id": 1,
         "payment_account_label": 1, "payment_reference": 1},
    ).sort("created_at", -1).to_list(5000)
    for d in docs:
        d["kind"] = "order"
    return docs


async def load_pending_batch_items(currency: str) -> List[Dict]:
    """iter172 — VIP batch items (Lotes VIP) are matching candidates too.
    The holder_name IS the bank sender the VIP declared per row. Mapped to
    the order-candidate shape so score_pair/rank work unchanged."""
    cur = currency.upper()
    docs = await db.vip_batch_items.find(
        {"status": "pending",
         "$or": [{"from_code": cur},
                 {"from_code": None, "currency": cur, "direction": "credit"}]},
        {"_id": 0, "id": 1, "batch_id": 1, "vip_user_id": 1, "holder_name": 1,
         "amount": 1, "currency": 1, "from_code": 1, "to_code": 1,
         "created_at": 1, "status": 1, "payment_account_id": 1,
         "payment_account_label": 1, "payment_reference": 1},
    ).sort("created_at", -1).to_list(5000)
    return [{
        "kind": "vip_batch_item",
        "id": it["id"],
        "batch_id": it.get("batch_id"),
        "user_id": it.get("vip_user_id"),
        "user_name": "",
        "user_email": "",
        "sender_name": it.get("holder_name") or "",
        "amount_from": it.get("amount"),
        "from_code": it.get("from_code") or it.get("currency"),
        "to_code": it.get("to_code"),
        "created_at": it.get("created_at"),
        "status": it.get("status"),
        "payment_account_id": it.get("payment_account_id"),
        "payment_account_label": it.get("payment_account_label"),
        "payment_reference": it.get("payment_reference") or "",
    } for it in docs]


def _passes_prefilters(o: Dict, tx_date: Optional[datetime], cfg: Dict,
                       import_bank_account_id: str, taken: set) -> bool:
    """Phase 1 filters (§34-35): taken set, hard account gate, date window."""
    if o["id"] in taken:
        return False
    # §11 hard gate only when the operator explicitly requires it
    # (iter175): real statements often can't identify the account.
    if (cfg.get("require_account_match")
            and import_bank_account_id and o.get("payment_account_id")
            and o["payment_account_id"] != import_bank_account_id):
        return False
    o_date = _iso_date(o.get("created_at"))
    if tx_date and o_date:
        # iter195.1 — symmetric window: bank payments often happen DAYS
        # BEFORE the order is registered in the system (client pays first,
        # order recorded later). The old `delta < -1` gate silently
        # discarded every statement row older than the order date
        # (operator report: 10-row AED statement → only 1 identified).
        if abs((tx_date - o_date).days) > int(cfg["date_window_days"]):
            return False
    return True


def _candidate_row(o: Dict, s: Dict) -> Dict:
    return {
        "order_id": o["id"], "kind": o.get("kind", "order"),
        "score": s["score"],
        "breakdown": s["breakdown"],
        "amount_exact": s["amount_exact"],
        "amount_within_tolerance": s["amount_within_tolerance"],
        "amount_delta": s["amount_delta"],
        "order_status": o.get("status"),
        "order_user_id": o.get("user_id"),
        "order_batch_id": o.get("batch_id"),
        "order_amount": o.get("amount_from"),
        "order_user_name": o.get("user_name"),
        "order_sender_name": o.get("sender_name"),
        "order_created_at": o.get("created_at"),
        "order_payment_reference": o.get("payment_reference") or "",
        "payment_account_id": o.get("payment_account_id"),
        "payment_account_label": o.get("payment_account_label"),
    }


def rank_candidates(tx: Dict, orders: List[Dict], cfg: Dict,
                    import_bank_account_id: str, taken: set) -> List[Dict]:
    """Phase 1 filters (§34-35): currency pre-filtered, hard account gate,
    date window. Phase 2: full scoring."""
    tx_date = _iso_date(tx.get("transaction_date"))
    ranked = []
    for o in orders:
        if not _passes_prefilters(o, tx_date, cfg, import_bank_account_id, taken):
            continue
        s = score_pair(tx, o, cfg)
        if s["score"] >= 40:  # keep the list small but informative
            ranked.append(_candidate_row(o, s))
    # V2: a igual score gana el candidato cuya referencia RB aparece en el
    # concepto (la referencia ya no suma al total, pero sí desempata).
    ranked.sort(key=lambda c: (-c["score"],
                               -(c["breakdown"].get("reference_score") or 0)))
    return ranked[:5]


def _amount_flag(best: Dict) -> Optional[str]:
    if best["amount_exact"]:
        return None
    delta = best.get("amount_delta") or 0
    return "possible_overpayment" if delta > 0 else "possible_partial_payment"


def _below_review_verdict(best: Dict, flag: Optional[str]) -> Dict[str, Any]:
    """iter172 safety-net: exact amount + close date but weak/no name match
    → surface for human review instead of burying it in "sin identificar"
    (the operator expects to SEE these)."""
    if best["amount_exact"] and (best["breakdown"].get("date_score") or 0) > 0:
        return {"decision": "review", "flag": flag or "name_mismatch",
                "block_reasons": ["score_below_auto"]}
    return {"decision": "unmatched", "flag": flag, "block_reasons": []}


def _config_gate_reasons(best: Dict, cfg: Dict, flag: Optional[str]) -> List[str]:
    reasons = []
    if not cfg["auto_match_enabled"]:
        reasons.append("auto_disabled")
    if best["score"] < cfg["auto_match_score"]:
        reasons.append("score_below_auto")
    if not best["amount_exact"] and (cfg["require_exact_amount"] or flag is not None):
        reasons.append("amount_not_exact")  # §46-47 never auto
    return reasons


def _ambiguity_reason(best: Dict, second: Optional[Dict], cfg: Dict) -> List[str]:
    """V2: si solo el mejor candidato tiene la referencia RB en el concepto,
    la ambigüedad queda resuelta a su favor."""
    if second is None:
        return []
    ref_edge = ((best["breakdown"].get("reference_score") or 0) >= 20
                and (second["breakdown"].get("reference_score") or 0) == 0)
    if not ref_edge and (best["score"] - second["score"]) < cfg["minimum_score_difference"]:
        return ["ambiguous_candidates"]
    return []


def _cap_and_status_reasons(tx: Dict, best: Dict, cfg: Dict) -> List[str]:
    reasons = []
    if (float(cfg["max_auto_confirmation_amount"] or 0) > 0
            and float(tx.get("amount") or 0) > float(cfg["max_auto_confirmation_amount"])):
        reasons.append("over_amount_cap")
    if best.get("order_status") != "pending":
        reasons.append("order_not_pending")
    return reasons


def _account_gate_reason(best: Dict, cfg: Dict,
                         import_bank_account_id: str) -> List[str]:
    """§13: receiving account must match — only when the rule is enabled
    (iter175: OFF by default, real statements rarely identify the account)."""
    if cfg.get("require_account_match") and not (
            import_bank_account_id and best.get("payment_account_id")
            and best["payment_account_id"] == import_bank_account_id):
        return ["account_mismatch"]
    return []


def _is_same_sender_multiple_users(best: Dict, second: Dict) -> bool:
    """V2 (pedido usuario): mismo remitente cumpliendo todo en órdenes de DOS
    usuarios distintos → siempre revisión humana (posible identidad compartida)."""
    return bool(best.get("order_user_id") and second.get("order_user_id")
                and best["order_user_id"] != second["order_user_id"])


def _is_duplicate_across_batches(best: Dict, second: Dict) -> bool:
    """Spec V2 apellidos: misma combinación nombre+monto+fecha en LOTES
    distintos → nunca auto (sin excepción por referencia)."""
    return bool((best["breakdown"].get("date_score") or 0) > 0
                and (second["breakdown"].get("date_score") or 0) > 0
                and best.get("kind") == "vip_batch_item"
                and second.get("kind") == "vip_batch_item"
                and best.get("order_batch_id") and second.get("order_batch_id")
                and best["order_batch_id"] != second["order_batch_id"])


def _duplicate_reasons(best: Dict, second: Optional[Dict]) -> List[str]:
    if second is None or not (best["amount_exact"] and second["amount_exact"]):
        return []
    reasons = []
    # §45: same amount + similar name on 2+ orders without reference.
    if (best["breakdown"]["reference_score"] == 0
            and abs(best["breakdown"]["name_score"] - second["breakdown"]["name_score"]) <= 5):
        reasons.append("duplicate_name_amount")
    both_strong_names = (best["breakdown"]["name_score"] >= 23
                         and second["breakdown"]["name_score"] >= 23)
    if both_strong_names and _is_same_sender_multiple_users(best, second):
        reasons.append("same_sender_multiple_users")
    if both_strong_names and _is_duplicate_across_batches(best, second):
        reasons.append("duplicate_across_batches")
    return reasons


def _surname_gate_reason(best: Dict, cfg: Dict) -> List[str]:
    """Spec V2 apellidos: el apellido es requisito OBLIGATORIO para auto."""
    if (best["breakdown"].get("surname_similarity") or 0) < float(
            cfg.get("surname_match_threshold", 0.75)):
        return ["surname_mismatch"]
    return []


def decide(tx: Dict, candidates: List[Dict], cfg: Dict,
           import_bank_account_id: str) -> Dict[str, Any]:
    """§12-§14, §44-§47, §62. Returns {decision, flag}."""
    if not candidates:
        return {"decision": "unmatched", "flag": None}
    best = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None

    flag = _amount_flag(best)
    if best["score"] < cfg["manual_review_score"]:
        return _below_review_verdict(best, flag)

    # iter174 — every blocker records WHY so the operator can see the exact
    # reason a movement stopped short of auto-confirmation.
    reasons = (_config_gate_reasons(best, cfg, flag)
               + _ambiguity_reason(best, second, cfg)
               + _cap_and_status_reasons(tx, best, cfg)
               + _account_gate_reason(best, cfg, import_bank_account_id)
               + _duplicate_reasons(best, second)
               + _surname_gate_reason(best, cfg))
    if reasons:
        if flag is None and "surname_mismatch" in reasons:
            flag = "surname_mismatch"
        return {"decision": "review", "flag": flag, "block_reasons": reasons}
    return {"decision": "auto", "flag": flag, "block_reasons": []}


async def recon_audit(action: str, actor: Dict, tx: Optional[Dict] = None,
                      order_id: Optional[str] = None, prev_status: Optional[str] = None,
                      new_status: Optional[str] = None, score: Optional[float] = None,
                      details: Optional[Dict] = None, import_id: Optional[str] = None,
                      ip: Optional[str] = None) -> None:
    """§23 — dedicated reconciliation_audit_log (never deleted)."""
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
    from services.orders_helpers import run_post_status_side_effects

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
        await publish_order_status_sse(order["id"], updated, "approved", prev_status)
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


async def approve_batch_item_from_reconciliation(item_id: str, tx: Dict,
                                                 actor: Dict, auto: bool) -> Dict:
    """iter172 — atomic pending→approved for a VIP batch item with
    reconciliation stamps. The filtered pre-claim IS the idempotency lock."""

    note = (f"Conciliación bancaria {'automática' if auto else 'manual'} — "
            f"movimiento {tx['id']} ({tx.get('transaction_date')}, "
            f"{tx.get('amount')} {tx.get('currency')})")
    res = await db.vip_batch_items.update_one(
        {"id": item_id, "status": "pending",
         "reconciliation.bank_transaction_id": {"$exists": False}},
        {"$set": {
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
        raise RuntimeError("item_no_longer_pending")
    try:
        fresh = await apply_item_decision(item_id, "approved", actor, admin_note=note)
    except Exception as e:
        await db.vip_batch_items.update_one(
            {"id": item_id},
            {"$unset": {"reconciliation": "", "payment_confirmation_source": "",
                        "bank_transaction_id": "", "reconciliation_score": ""}})
        logger.error(f"reconciliation item approval failed for {item_id}: {e!r}")
        raise RuntimeError(f"item_approval_failed: {e}")
    try:
        await log_action(
            db, actor, "vip_batch_item.reconciled", "vip_batch_item", item_id,
            summary=(f"Ítem de lote conciliado {'automáticamente' if auto else 'manualmente'} "
                     f"con movimiento bancario {tx['id']}"),
            details={"bank_transaction_id": tx["id"], "auto": auto,
                     "score": tx.get("confidence_score"),
                     "amount": tx.get("amount"), "currency": tx.get("currency"),
                     "holder_name": fresh.get("holder_name")},
        )
    except Exception as e:
        logger.error(f"reconciliation item audit failed: {e}")
    try:
        await notify_vip_item_decision(fresh, approved=True)
    except Exception as e:
        logger.error(f"reconciliation item notify failed: {e}")
    return fresh


async def rollback_batch_item_from_reconciliation(item: Dict, tx_id: str,
                                                  actor: Dict, reason: str) -> None:
    """iter172 §25 — revert a batch-item reconciliation: reverse the credited
    balance and return the item to pending."""
    if item.get("to_code"):
        amount_to = float(item.get("amount_to") or 0.0)
        if amount_to > 0:
            await db.users.update_one(
                {"user_id": item["vip_user_id"]},
                {"$inc": {f"vip_balances.{item['to_code']}": -amount_to}})
    else:
        delta = float(item.get("balance_delta_usdt") or 0.0)
        if delta:
            field = ("positive_usdt" if item.get("direction") == "credit"
                     else "negative_usdt")
            await db.vip_ledger.update_one(
                {"vip_user_id": item["vip_user_id"]},
                {"$inc": {field: -delta},
                 "$set": {"updated_at": iso(now_utc())}})
    await db.vip_batch_items.update_one(
        {"id": item["id"]},
        {"$set": {"status": "pending", "updated_at": iso(now_utc()),
                  "reviewed_at": None, "reviewed_by": None,
                  "balance_delta_usdt": None, "margin_usdt": None,
                  "admin_note": f"Rollback de conciliación: {reason}"},
         "$unset": {"reconciliation": "", "payment_confirmation_source": "",
                    "bank_transaction_id": "", "reconciliation_score": ""}})
    await refresh_batch_totals(item["batch_id"])
    try:
        from services.live_bus import publish as live_publish
        await live_publish(
            "vip_batch_item_decision",
            {"item_id": item["id"], "batch_id": item["batch_id"],
             "decision": "pending"},
            user_id=item["vip_user_id"])
        await live_publish(
            "balance_updated",
            {"reason": "reconciliation_rollback", "item_id": item["id"],
             "currency": item.get("to_code") or item.get("currency")},
            user_id=item["vip_user_id"])
    except Exception as e:
        logger.error(f"reconciliation rollback SSE failed: {e}")


async def _apply_auto_match(tx: Dict, best: Dict, pool: List[Dict],
                            update: Dict, taken: set, actor: Dict,
                            prev_status: str) -> str:
    """Persists an auto decision; falls back to manual review on any
    RuntimeError (order/item no longer pending, vanished candidate...)."""
    cand_doc = next((o for o in pool if o["id"] == best["order_id"]), None)
    try:
        tx["confidence_score"] = best["score"]
        if cand_doc is None:
            raise RuntimeError("candidate order vanished from pool between rank and apply")
        if cand_doc.get("kind") == "vip_batch_item":
            await approve_batch_item_from_reconciliation(
                cand_doc["id"], tx, actor, auto=True)
        else:
            await approve_order_from_reconciliation(
                cand_doc, tx, actor, auto=True)
    except RuntimeError as e:
        logger.warning(f"auto-match fallback to review for tx {tx['id']}: {e}")
        update["status"] = "manual_review"
        return "review"
    update.update({"status": "auto_matched",
                   "matched_order_id": best["order_id"],
                   "matched_kind": cand_doc.get("kind", "order"),
                   "match_details": best,
                   "matched_at": iso(now_utc()),
                   "matched_by": "system_reconciliation",
                   "reviewed_by": "system_reconciliation",
                   "reviewed_at": iso(now_utc())})
    taken.add(best["order_id"])
    await recon_audit("AUTO_MATCHED", actor, tx=tx,
                      order_id=best["order_id"],
                      prev_status=prev_status, new_status="auto_matched",
                      score=best["score"], details=best["breakdown"])
    return "auto"


async def _match_and_apply(tx: Dict, pool: List[Dict], cfg: Dict,
                           bank_account_id: str, taken: set,
                           actor: Dict) -> str:
    """Ranks, decides and persists the outcome for ONE credit transaction.
    Returns the decision bucket: auto | review | unmatched."""
    candidates = rank_candidates(tx, pool, cfg, bank_account_id, taken)
    verdict = decide(tx, candidates, cfg, bank_account_id)
    best = candidates[0] if candidates else None
    prev_status = tx.get("status") or "unprocessed"
    update = {
        "candidates": candidates,
        "confidence_score": best["score"] if best else 0,
        "review_flag": verdict["flag"],
        "auto_block_reasons": verdict.get("block_reasons") or [],
        "algorithm_version": ALGORITHM_VERSION,
        "updated_at": iso(now_utc()),
    }
    decision = verdict["decision"]
    if decision == "auto":
        assert best is not None  # decide() returns "auto" only when a candidate ranks
        decision = await _apply_auto_match(tx, best, pool, update, taken,
                                           actor, prev_status)
    elif decision == "review":
        update["status"] = "manual_review"
        if best and prev_status != "manual_review":
            await recon_audit("MATCH_SUGGESTED", actor, tx=tx,
                              order_id=best["order_id"],
                              new_status="manual_review",
                              score=best["score"], details=best["breakdown"])
    else:
        update["status"] = "unmatched"
    await db.bank_transactions.update_one({"id": tx["id"]}, {"$set": update})
    return decision


async def run_matching(import_doc: Dict, tx_docs: List[Dict]) -> Dict[str, int]:
    """Matches freshly-imported CREDIT transactions. Mutates tx docs in DB."""
    cfg = await get_config()
    pool = (await load_pending_orders(import_doc["currency"])) + \
           (await load_pending_batch_items(import_doc["currency"]))
    bank_account_id = import_doc.get("bank_account_id") or ""
    taken: set = set()
    counts = {"auto": 0, "review": 0, "unmatched": 0}
    for tx in tx_docs:
        if tx.get("direction") != "credit" or tx.get("status") in ("duplicate", "error"):
            continue
        counts[await _match_and_apply(tx, pool, cfg, bank_account_id,
                                      taken, SYSTEM_ACTOR)] += 1
    return counts


async def _refresh_import_counters(import_id: str) -> None:
    agg = {r["_id"]: r["n"] async for r in db.bank_transactions.aggregate([
        {"$match": {"statement_import_id": import_id}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}}])}
    await db.bank_statement_imports.update_one(
        {"id": import_id},
        {"$set": {
            "total_auto_matched": agg.get("auto_matched", 0) + agg.get("manual_matched", 0),
            "total_manual_review": agg.get("manual_review", 0),
            "total_unmatched": agg.get("unmatched", 0),
            "updated_at": iso(now_utc()),
        }})


async def rematch_transactions(actor: Dict, currency: Optional[str] = None,
                               import_id: Optional[str] = None) -> Dict[str, int]:
    """iter174 — re-runs the matching engine over movements still in
    unmatched/manual_review against the CURRENT pending orders and batch
    items. Makes reconciliation order-independent: statements imported
    BEFORE the orders/items existed get matched as soon as this runs."""
    q: Dict[str, Any] = {"status": {"$in": ["unmatched", "manual_review"]},
                         "direction": "credit"}
    if currency:
        q["currency"] = currency.upper()
    if import_id:
        q["statement_import_id"] = import_id
    txs = await db.bank_transactions.find(q, {"_id": 0, "raw": 0}) \
        .sort([("transaction_date", 1), ("created_at", 1)]).to_list(5000)
    counts = {"scanned": len(txs), "auto": 0, "review": 0, "unmatched": 0}
    if not txs:
        return counts
    cfg = await get_config()
    pools: Dict[str, List[Dict]] = {}
    taken: set = set()
    affected_imports = set()
    for tx in txs:
        cur = (tx.get("currency") or "").upper()
        if cur not in pools:
            pools[cur] = (await load_pending_orders(cur)) + \
                         (await load_pending_batch_items(cur))
        counts[await _match_and_apply(
            tx, pools[cur], cfg, tx.get("bank_account_id") or "",
            taken, actor)] += 1
        if tx.get("statement_import_id"):
            affected_imports.add(tx["statement_import_id"])
    for imp_id in affected_imports:
        await _refresh_import_counters(imp_id)
    logger.info(f"rematch: {counts}")
    return counts


def schedule_rematch(currency: Optional[str] = None) -> None:
    """Fire-and-forget rematch, called right after an order/batch item is
    created so movements imported earlier confirm automatically."""
    import asyncio

    async def _run() -> None:
        try:
            await rematch_transactions(SYSTEM_ACTOR, currency=currency)
        except Exception as e:
            logger.error(f"background rematch failed: {e}")

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        logger.error("schedule_rematch: no running event loop")
