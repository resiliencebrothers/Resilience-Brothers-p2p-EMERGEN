"""iter195.1 — Reconciliation date-window regression.

Operator report: a 10-row AED statement matched only 1 order. Root cause:
`rank_candidates` discarded any bank payment older than 1 day BEFORE the
order's created_at (`delta < -1`). Real flow: clients pay first, orders get
registered later — the window must be symmetric (±date_window_days).
"""
from services.reconciliation_matcher import (DEFAULT_CONFIG, decide,
                                             rank_candidates)


def _tx(date, name, amount):
    return {"transaction_date": date, "sender_name": name, "amount": amount,
            "currency": "AED", "description": None, "reference": None}


def _order(oid, date, name, amount):
    return {"id": oid, "kind": "order", "status": "pending",
            "user_id": f"u_{oid}", "user_name": name, "sender_name": name,
            "user_email": "", "amount_from": amount, "from_code": "AED",
            "created_at": f"{date}T09:00:00+00:00", "payment_reference": ""}


def test_payment_days_before_order_creation_still_matches():
    """Statement row 8 days OLDER than the order must be a candidate."""
    cfg = dict(DEFAULT_CONFIG)
    orders = [_order("o1", "2026-08-10", "Miguel Torres", 86.0)]
    ranked = rank_candidates(_tx("2026-08-02", "Miguel Torres", 86.0),
                             orders, cfg, "", set())
    assert len(ranked) == 1
    assert ranked[0]["order_id"] == "o1"
    assert ranked[0]["amount_exact"] is True
    d = decide(_tx("2026-08-02", "Miguel Torres", 86.0), ranked, cfg, "")
    assert d["decision"] == "auto", d


def test_full_statement_scenario_all_rows_get_candidates():
    """The exact AED simulated-statement scenario: 10 rows dated 02-09 Aug,
    10 orders registered 10 Aug → every row must find its order."""
    cfg = dict(DEFAULT_CONFIG)
    rows = [("2026-08-02", "Miguel Torres", 86.0),
            ("2026-08-03", "Daniel Herrera", 50.0),
            ("2026-08-03", "Carlos Benitez", 61.0),
            ("2026-08-03", "Sofia Ramirez", 67.0),
            ("2026-08-03", "Camila Fernandez", 72.0),
            ("2026-08-04", "Andrea Castillo", 57.0),
            ("2026-08-04", "Alejandro Navarro", 50.0),
            ("2026-08-06", "Valentina Rojas", 74.0),
            ("2026-08-07", "Javier Morales", 59.0),
            ("2026-08-09", "Laura Mendoza", 51.0)]
    orders = [_order(f"o{i}", "2026-08-10", n, a)
              for i, (_, n, a) in enumerate(rows)]
    taken: set = set()
    auto = 0
    for date, name, amount in rows:
        tx = _tx(date, name, amount)
        ranked = rank_candidates(tx, orders, cfg, "", taken)
        assert ranked, f"no candidates for {name} {date}"
        d = decide(tx, ranked, cfg, "")
        if d["decision"] == "auto":
            auto += 1
            taken.add(ranked[0]["order_id"])
    assert auto == 10


def test_window_still_bounds_old_payments():
    """Payments beyond ±date_window_days stay excluded (no over-matching)."""
    cfg = dict(DEFAULT_CONFIG)  # window = 14 days
    orders = [_order("o1", "2026-08-10", "Miguel Torres", 86.0)]
    ranked = rank_candidates(_tx("2026-07-10", "Miguel Torres", 86.0),
                             orders, cfg, "", set())
    assert ranked == []
    ranked = rank_candidates(_tx("2026-09-10", "Miguel Torres", 86.0),
                             orders, cfg, "", set())
    assert ranked == []
