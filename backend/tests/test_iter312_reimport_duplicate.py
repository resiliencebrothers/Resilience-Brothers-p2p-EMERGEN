"""iter312 — Re-importación del MISMO extracto en otro formato (PDF vs Excel).

Bug reportado por el operador: al subir el mismo extracto bancario en PDF y en
Excel, el sistema procesa los dos y crea movimientos con nombres duplicados;
el segundo NO recibe puntuación, no aprueba a uno de los dos ni lo manda a
revisión — queda atascado como 'sin identificar'.

La huella exacta difiere entre formatos (referencia/concepto se extraen
distinto), así que el dedupe por huella no lo atrapa. La identidad ECONÓMICA sí
es estable: misma cuenta, moneda, dirección, importe EXACTO, fecha (±3 días) y
remitente equivalente. Cuando un abono quedaría 'sin identificar' PERO su
gemelo económico YA está conciliado, se marca como 'duplicate' vinculado al
original (jamás acredita dos veces), en lugar de dejarlo atascado.

El respaldo SOLO actúa cuando el movimiento no tiene ninguna orden pendiente
que casar (decisión 'unmatched'): un pago genuino con su propia orden
pendiente sigue casando con normalidad y nunca se marca como duplicado.

Nota de infra: el cliente Motor compartido (`db_client.db`) se enlaza al primer
loop que lo usa, así que cada método hace TODO su trabajo async dentro de un
único `_run` (un solo loop por método), igual que las suites de conciliación
existentes.
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient

MARK = "iter312"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def setup_module():
    _cleanup()


def teardown_module():
    _cleanup()


def _cleanup():
    db = _db()
    db.orders.delete_many({"id": {"$regex": f"^ord{MARK}"}})
    db.bank_transactions.delete_many({"id": {"$regex": f"^btx{MARK}"}})
    db.settings.delete_one({"id": "reconciliation_config"})


def _mk_order(order_id, amount=137.0, name="ANA PEREZ GARCIA", currency="USD",
              status="pending"):
    doc = {
        "id": order_id, "user_id": f"u{order_id}",
        "user_name": name, "user_email": f"{order_id[:12]}@t.com",
        "sender_name": name,
        "amount_from": float(amount), "amount_to": float(amount) * 300,
        "from_code": currency, "to_code": "CUP", "status": status,
        "payment_account_id": None, "payment_account_label": "Zelle",
        "created_at": _now(), "updated_at": _now(),
    }
    _db().orders.insert_one(dict(doc))
    return doc


def _mk_tx(suffix, amount=137.0, currency="USD", sender="ANA PEREZ GARCIA",
           description=None, reference=None, tx_date=None, status="unmatched",
           insert=True, **extra):
    doc = {
        "id": f"btx{MARK}{suffix}",
        "statement_import_id": f"{MARK}_imp_{suffix}",
        "bank_account_id": None, "bank_name": "Test Bank",
        "currency": currency, "direction": "credit", "amount": float(amount),
        "transaction_date": tx_date or _today(), "sender_name": sender,
        "description": description, "reference": reference,
        "fingerprint": f"fp_{uuid.uuid4().hex}",
        "fingerprint_original": f"fpo_{suffix}_{uuid.uuid4().hex[:8]}",
        "status": status, "confidence_score": None,
        "matched_order_id": None, "match_details": None, "candidates": [],
        "reviewed_by": None, "reviewed_at": None, "raw": {},
        "created_at": _now(), "updated_at": _now(),
    }
    doc.update(extra)
    if insert:
        _db().bank_transactions.insert_one(dict(doc))
    return doc


async def _match(tx_doc):
    from services.reconciliation_matcher import run_matching
    return await run_matching(
        {"currency": tx_doc["currency"], "bank_account_id": None}, [tx_doc])


class TestReimportDuplicate:
    def test_second_format_import_marked_duplicate(self):
        """PDF crea el abono → auto-concilia. Excel (mismo pago, huella
        distinta) queda 'unmatched' pero su gemelo ya conciliado lo convierte
        en 'duplicate' vinculado al original — nunca atascado sin puntuar."""
        db = _db()
        oid = f"ord{MARK}A"
        _mk_order(oid)
        tx_pdf = _mk_tx("Apdf", reference="REF-9931",
                        description="TRANSFERENCIA DE ANA PEREZ GARCIA")
        tx_xls = _mk_tx("Axls", reference=None,
                        description="Abono transferencia")

        async def flow():
            c1 = await _match(tx_pdf)
            c2 = await _match(tx_xls)
            return c1, c2
        c1, c2 = _run(flow())

        assert c1["auto"] == 1, c1
        fa = db.bank_transactions.find_one({"id": tx_pdf["id"]})
        assert fa["status"] == "auto_matched"
        assert db.orders.find_one({"id": oid})["status"] == "approved"

        assert c2["duplicate"] == 1, c2
        assert c2["unmatched"] == 0, c2
        fb = db.bank_transactions.find_one({"id": tx_xls["id"]})
        assert fb["status"] == "duplicate", fb.get("status")
        assert fb.get("duplicate_of") == tx_pdf["id"]
        assert fb.get("duplicate_reason") == "reimport_same_payment"

    def test_genuine_second_payment_with_pending_order_not_marked_duplicate(self):
        """Seguridad: dos pagos con la misma identidad económica pero DOS
        órdenes pendientes NO se marcan como duplicados — el segundo tiene su
        propia orden que casar (aunque la ambigüedad lo lleve a revisión)."""
        db = _db()
        oid1, oid2 = f"ord{MARK}B1", f"ord{MARK}B2"
        _mk_order(oid1, amount=222.0, name="LUIS TORRES MENDEZ")
        _mk_order(oid2, amount=222.0, name="LUIS TORRES MENDEZ")
        tx1 = _mk_tx("B1", amount=222.0, sender="LUIS TORRES MENDEZ")
        tx2 = _mk_tx("B2", amount=222.0, sender="LUIS TORRES MENDEZ")

        async def flow():
            await _match(tx1)
            return await _match(tx2)
        c2 = _run(flow())

        f2 = db.bank_transactions.find_one({"id": tx2["id"]})
        assert f2["status"] != "duplicate", f2.get("status")
        assert c2["duplicate"] == 0, c2

    def test_different_sender_is_not_a_twin(self):
        """Conservador: mismo importe/fecha pero remitente DISTINTO no es
        gemelo — no se colapsan pagos de personas diferentes."""
        db = _db()
        oid = f"ord{MARK}C"
        _mk_order(oid, amount=88.0, name="MARIA GOMEZ SILVA")
        tx_ok = _mk_tx("Cok", amount=88.0, sender="MARIA GOMEZ SILVA")
        tx_other = _mk_tx("Cother", amount=88.0, sender="PEDRO RUIZ CASTILLO")

        async def flow():
            await _match(tx_ok)
            return await _match(tx_other)
        c = _run(flow())

        assert db.bank_transactions.find_one(
            {"id": tx_ok["id"]})["status"] == "auto_matched"
        f = db.bank_transactions.find_one({"id": tx_other["id"]})
        assert f["status"] != "duplicate", f.get("status")
        assert c["duplicate"] == 0, c

    def test_twin_only_when_original_reconciled(self):
        """El gemelo debe estar CONCILIADO (auto/manual). Un movimiento en
        revisión/sin identificar no dispara el marcado de duplicado."""
        _mk_tx("Dreview", amount=54.0, sender="JORGE LEON DIAZ",
               status="manual_review")
        tx_probe = {"id": f"btx{MARK}Dprobe", "amount": 54.0,
                    "currency": "USD", "direction": "credit",
                    "transaction_date": _today(),
                    "sender_name": "JORGE LEON DIAZ", "bank_account_id": None}

        async def flow():
            from services.reconciliation_matcher import (
                find_reconciled_economic_twin)
            before = await find_reconciled_economic_twin(tx_probe)
            _mk_tx("Dmatched", amount=54.0, sender="JORGE LEON DIAZ",
                   status="manual_matched", matched_order_id="ordX")
            after = await find_reconciled_economic_twin(tx_probe)
            return before, after
        before, after = _run(flow())

        assert before is None, "un gemelo no conciliado no cuenta"
        assert after is not None and after["id"] == f"btx{MARK}Dmatched"

    def test_twin_tolerates_date_shift_and_description_sender(self):
        """La ventana de fecha (±3 días) tolera fecha operación vs valor entre
        formatos; el remitente puede venir del concepto (extractos ES)."""
        db = _db()
        oid = f"ord{MARK}E"
        _mk_order(oid, amount=310.0, name="CARLOS MARTINEZ ROJAS")
        tx_pdf = _mk_tx("Epdf", amount=310.0, sender=None,
                        description="ABONO TRANSFERENCIA DE CARLOS MARTINEZ ROJAS",
                        tx_date=_today())
        shifted = (datetime.now(timezone.utc).date()
                   + timedelta(days=2)).isoformat()
        tx_xls = _mk_tx("Exls", amount=310.0, sender="CARLOS MARTINEZ ROJAS",
                        description="Transferencia recibida", tx_date=shifted)

        async def flow():
            c1 = await _match(tx_pdf)
            c2 = await _match(tx_xls)
            return c1, c2
        c1, c2 = _run(flow())

        assert c1["auto"] == 1, c1
        assert c2["duplicate"] == 1, c2
        assert db.bank_transactions.find_one(
            {"id": tx_xls["id"]})["duplicate_of"] == tx_pdf["id"]
