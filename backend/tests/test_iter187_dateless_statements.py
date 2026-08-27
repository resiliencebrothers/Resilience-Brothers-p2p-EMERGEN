"""iter187 — Date-less statements (e.g. Zelle registries without a date
column) must still be extracted; the matcher skips date scoring for them.
"""
import json

from services.reconciliation_parser import _parse_llm_json


def test_llm_rows_without_date_are_kept():
    raw = json.dumps([
        {"transaction_date": None, "time": None, "amount": 761.0,
         "direction": "credit", "sender_name": "Fidel Castro",
         "beneficiary_name": None, "description": None, "reference": None,
         "balance_after": None, "payment_method": "Zelle"},
        {"transaction_date": "2099-03-01", "amount": 100.0,
         "direction": "credit", "sender_name": "Ana"},
        {"transaction_date": None, "amount": 0, "direction": "credit",
         "sender_name": "invalid-zero-amount"},
    ])
    txs = _parse_llm_json(raw)
    assert len(txs) == 2
    assert txs[0]["transaction_date"] is None
    assert txs[0]["amount"] == 761.0
    assert txs[0]["sender_name"] == "Fidel Castro"
    assert txs[1]["transaction_date"] == "2099-03-01"


def test_llm_rows_carry_row_index_for_fingerprint_uniqueness():
    raw = json.dumps([
        {"transaction_date": None, "amount": 100.0, "direction": "credit",
         "sender_name": "Juan Perez"},
        {"transaction_date": None, "amount": 100.0, "direction": "credit",
         "sender_name": "Juan Perez"},
    ])
    txs = _parse_llm_json(raw)
    assert len(txs) == 2
    assert txs[0]["row_index"] != txs[1]["row_index"]
