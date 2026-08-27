"""iter174 — Re-matching de movimientos no resueltos.

Root cause (reporte del usuario x2): el matching solo corría al IMPORTAR el
extracto. Si las órdenes/lotes se creaban después del import (el flujo real),
los movimientos quedaban en "sin identificar" para siempre, y re-subir el
mismo PDF se rechaza como duplicado.

Fixes:
  - POST /api/admin/reconciliation/rematch → re-ejecuta el matching sobre
    unmatched/manual_review contra las órdenes/ítems pendientes ACTUALES.
  - schedule_rematch() automático al crear órdenes normales y al agregar
    ítems a un lote VIP.
  - decide() ahora persiste auto_block_reasons (por qué no fue automático).
"""
import io
import os
import time
import uuid

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP

PACC_ID = "pacc_test174"
API = f"{BASE_URL}/api/admin/reconciliation"
VIP_ID = "user_test_vip01"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _upload(csv_text, filename):
    return requests.post(
        f"{API}/imports", headers=_h(ADMIN),
        files={"file": (filename, io.BytesIO(csv_text.encode()), "text/csv")},
        data={"bank_account_id": PACC_ID, "bank_name": "Wells Fargo",
              "currency": "USD"})


def _wait_processed(import_id, timeout=45):
    for _ in range(timeout):
        r = requests.get(f"{API}/imports/{import_id}", headers=_h(ADMIN))
        doc = r.json()
        if doc["processing_status"] not in ("uploaded", "processing"):
            return doc
        time.sleep(1)
    raise TimeoutError("import never finished")


def _mk_batch(db):
    batch_id = f"vbatch_t174_{uuid.uuid4().hex[:8]}"
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    db.vip_batches.insert_one({
        "id": batch_id, "vip_user_id": VIP_ID, "vip_email": "vip.test@resilience.com",
        "vip_name": "VIP Test", "direction": "pair", "currency": "USD",
        "from_code": "USD", "to_code": "USDT", "rate_vip": 0.95,
        "requires_card": False, "note": None, "status": "open",
        "items_pending": 0, "items_approved": 0, "items_rejected": 0,
        "amount_pending": 0.0, "amount_approved": 0.0,
        "created_at": now, "updated_at": now, "closed_at": None,
    })
    return batch_id


def _mk_item(db, batch_id, holder, amount):
    item_id = f"vitem_t174_{uuid.uuid4().hex[:8]}"
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    db.vip_batch_items.insert_one({
        "id": item_id, "batch_id": batch_id, "vip_user_id": VIP_ID,
        "holder_name": holder, "card_number": None,
        "amount": float(amount), "currency": "USD", "direction": "pair",
        "from_code": "USD", "to_code": "USDT",
        "rate_applied": 0.95, "amount_to": round(float(amount) * 0.95, 4),
        "payment_account_id": PACC_ID,
        "payment_account_label": "Zelle Test 174",
        "payment_reference": f"RB-{uuid.uuid4().int % 900000 + 100000}",
        "status": "pending", "admin_note": None, "balance_delta_usdt": None,
        "margin_usdt": None, "created_at": now, "updated_at": now,
        "reviewed_at": None, "reviewed_by": None,
    })
    return item_id


def _mk_order(db, order_id, amount, name):
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    db.orders.insert_one({
        "id": order_id, "user_id": "user_test_normal01",
        "user_name": name, "user_email": f"{order_id[:6]}@test.com",
        "sender_name": name, "payment_reference": "",
        "amount_from": float(amount), "amount_to": float(amount) * 300,
        "from_code": "USD", "to_code": "CUP", "status": "pending",
        "payment_account_id": PACC_ID,
        "payment_account_label": "Zelle Test 174",
        "created_at": now, "updated_at": now,
    })


def _cleanup():
    db = _db()
    imps = [i["id"] for i in db.bank_statement_imports.find(
        {"original_file_name": {"$regex": "^test174_"}}, {"id": 1})]
    db.bank_transactions.delete_many({"statement_import_id": {"$in": imps}})
    db.bank_statement_imports.delete_many({"id": {"$in": imps}})
    db.statement_files.delete_many({"id": {"$in": imps}})
    db.reconciliation_audit_log.delete_many({"statement_import_id": {"$in": imps}})
    db.orders.delete_many({"id": {"$regex": "^ord174"}})
    db.vip_batch_items.delete_many({"id": {"$regex": "^vitem_t174_"}})
    db.vip_batch_items.delete_many({"batch_id": {"$regex": "^vbatch_t174_"}})
    db.vip_batches.delete_many({"id": {"$regex": "^vbatch_t174_"}})
    db.rates.delete_many({"id": "rate_t174"})
    db.settings.delete_one({"id": "reconciliation_config"})


def setup_module():
    _cleanup()


def teardown_module():
    _cleanup()


class TestRematchEndpoint:
    def test_import_first_orders_after_then_rematch_auto_confirms(self):
        """Flujo real del usuario: extracto importado ANTES de que existan
        las órdenes → todo queda sin identificar → rematch los confirma."""
        db = _db()
        today = time.strftime("%Y-%m-%d")
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Transferencia recibida,137.29,ROSA MARIA TORRES\n"
                    f"{today},Transferencia recibida,262.47,PEDRO SANCHEZ MOLINA\n")
        r = _upload(csv_text, f"test174_{uuid.uuid4().hex[:6]}.csv")
        assert r.status_code == 200, r.text
        imp = _wait_processed(r.json()["id"])
        assert imp["total_unmatched"] == 2, imp
        assert imp["total_auto_matched"] == 0

        # Ahora aparecen la orden normal y el ítem de lote
        oid = f"ord174_{uuid.uuid4().hex[:8]}"
        _mk_order(db, oid, 137.29, "Rosa Maria Torres")
        batch_id = _mk_batch(db)
        item_id = _mk_item(db, batch_id, "Pedro Sanchez Molina", 262.47)

        rr = requests.post(f"{API}/rematch", headers=_h(ADMIN),
                           json={"import_id": imp["id"]})
        assert rr.status_code == 200, rr.text
        counts = rr.json()
        assert counts["scanned"] == 2, counts
        assert counts["auto"] == 2, counts

        assert db.orders.find_one({"id": oid})["status"] == "approved"
        item = db.vip_batch_items.find_one({"id": item_id})
        assert item["status"] == "approved"
        assert item["payment_confirmation_source"] == "BANK_RECONCILIATION"
        for tx in db.bank_transactions.find({"statement_import_id": imp["id"]}):
            assert tx["status"] == "auto_matched"
        # counters del import refrescados
        imp2 = requests.get(f"{API}/imports/{imp['id']}", headers=_h(ADMIN)).json()
        assert imp2["total_auto_matched"] == 2
        assert imp2["total_unmatched"] == 0

    def test_rematch_requires_permission(self):
        assert requests.post(f"{API}/rematch", json={}).status_code in (401, 403)


class TestAccountMatchToggle:
    def test_auto_without_account_by_default_and_gate_when_enabled(self):
        """iter175 — extractos reales (fotos → PDF) no identifican la cuenta:
        con el toggle OFF (default) nombre+monto+fecha bastan para auto;
        con el toggle ON la cuenta debe coincidir → revisión con motivo."""
        db = _db()
        today = time.strftime("%Y-%m-%d")

        # Caso 1: cuentas distintas + toggle OFF → AUTO
        oid = f"ord174_{uuid.uuid4().hex[:8]}"
        _mk_order(db, oid, 418.66, "Benito Camelo Fuentes")
        db.orders.update_one({"id": oid},
                             {"$set": {"payment_account_id": "pacc_OTRA"}})
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Transferencia Santander,418.66,BENITO CAMELO FUENTES\n")
        imp = _wait_processed(_upload(
            csv_text, f"test174_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_auto_matched"] == 1, imp
        assert db.orders.find_one({"id": oid})["status"] == "approved"

        # Caso 2: toggle ON → misma situación queda en revisión con motivo
        rc = requests.put(f"{API}/config", headers=_h(ADMIN),
                          json={"require_account_match": True})
        assert rc.status_code == 200, rc.text
        assert rc.json()["require_account_match"] is True
        oid2 = f"ord174_{uuid.uuid4().hex[:8]}"
        _mk_order(db, oid2, 512.34, "Ramona Quintero Vega")
        db.orders.update_one({"id": oid2},
                             {"$set": {"payment_account_id": "pacc_OTRA"}})
        csv2 = ("Date,Description,Amount,Sender\n"
                f"{today},Transferencia Santander,512.34,RAMONA QUINTERO VEGA\n")
        imp2 = _wait_processed(_upload(
            csv2, f"test174_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp2["total_auto_matched"] == 0, imp2
        assert db.orders.find_one({"id": oid2})["status"] == "pending"
        requests.put(f"{API}/config", headers=_h(ADMIN),
                     json={"require_account_match": False})


class TestAutoRematchHook:
    def test_adding_batch_item_via_api_triggers_rematch(self):
        """Al agregar un ítem al lote por el API del VIP, el hook de fondo
        re-procesa los movimientos: el tx pasa de unmatched → manual_review
        (no auto porque el ítem creado por API no tiene la cuenta del import)
        y registra auto_block_reasons."""
        db = _db()
        today = time.strftime("%Y-%m-%d")
        if not db.rates.find_one({"from_code": "USD", "to_code": "USDT"}):
            db.rates.insert_one({"id": "rate_t174", "from_code": "USD",
                                 "to_code": "USDT", "rate": 0.97,
                                 "rate_normal": 0.96,
                                 "rate_vip": 0.95, "active": True})
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Bizum recibido,91.83,CATALINA BRITO SUAREZ\n")
        imp = _wait_processed(_upload(
            csv_text, f"test174_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        tx = _db().bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] == "unmatched"

        batch_id = _mk_batch(db)
        ra = requests.post(f"{BASE_URL}/api/vip/batches/{batch_id}/items",
                           headers=_h(VIP),
                           json={"items": [{"holder_name": "Catalina Brito Suarez",
                                            "amount": 91.83}]})
        assert ra.status_code == 200, ra.text

        final = None
        for _ in range(16):
            final = db.bank_transactions.find_one({"id": tx["id"]}, {"_id": 0})
            if final["status"] != "unmatched":
                break
            time.sleep(0.5)
        assert final["status"] in ("manual_review", "auto_matched"), final["status"]
        assert final["candidates"], "hook did not attach candidates"
        assert final["candidates"][0]["kind"] == "vip_batch_item"
        if final["status"] == "manual_review":
            assert final.get("auto_block_reasons"), final
