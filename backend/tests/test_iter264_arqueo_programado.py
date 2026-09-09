"""iter264 — Arqueo Programado de la Caja de Efectivo.

Verifica:
1. `resumen.needs_arqueo`: True con actividad de hoy sin arqueo; False tras
   registrar el arqueo del día (y `arqueo_today` expuesto).
2. Un arqueo con faltante/sobrante en caja de EMPRESA alerta a los admins
   (campana in-app); cuadrada o caja personal → sin alerta.
3. `run_daily_arqueo_request`: pide el arqueo de los fondos de empresa con
   actividad y sin arqueo hoy; excluye cajas con arqueo del día y personales.
4. El job `daily_arqueo_request` está registrado en el scheduler.
"""
import asyncio
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER264"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _cleanup():
    db = _db()
    ids = [b["id"] for b in db.cash_boxes.find(
        {"name": {"$regex": MARK}}, {"_id": 0, "id": 1})]
    if ids:
        db.cash_box_movements.delete_many({"box_id": {"$in": ids}})
        db.cash_box_arqueos.delete_many({"box_id": {"$in": ids}})
        db.cash_boxes.delete_many({"id": {"$in": ids}})
    db.notifications.delete_many({
        "type": {"$in": ["cash_box_arqueo_diff", "cash_box_arqueo_due"]},
        "message": {"$regex": MARK}})


def _mk_box(scope="empresa"):
    r = requests.post(f"{API}/cashbox/boxes", headers=_hdr(ADMIN_TOKEN),
                      json={"name": f"{MARK} {uuid.uuid4().hex[:6]}",
                            "scope": scope})
    assert r.status_code == 200, r.text
    return r.json()


def _mk_mov(box_id, amount=1000, denoms=None, fund="CUP"):
    r = requests.post(f"{API}/cashbox/boxes/{box_id}/movimientos",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"fund": fund, "type": "entrada", "amount": amount,
                            "concept": f"venta {MARK}",
                            "denominations": denoms})
    assert r.status_code == 200, r.text
    return r.json()


def _arqueo(box_id, counted, fund="CUP", note=""):
    return requests.post(f"{API}/cashbox/boxes/{box_id}/arqueos",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"fund": fund, "counted": counted, "note": note})


def _resumen(box_id, fund="CUP"):
    r = requests.get(f"{API}/cashbox/boxes/{box_id}/resumen",
                     params={"fund": fund}, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()


def _run(async_fn):
    from db_client import client as _motor_client
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        _motor_client._io_loop = None
        return loop.run_until_complete(async_fn())
    finally:
        _motor_client._io_loop = None
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_needs_arqueo_flow():
    _cleanup()
    try:
        box = _mk_box()
        res = _resumen(box["id"])
        assert res["needs_arqueo"] is False, \
            "caja nueva sin actividad no pide arqueo"
        assert res["arqueo_today"] is None

        _mk_mov(box["id"], 1000, {"1000": 1})
        res = _resumen(box["id"])
        assert res["needs_arqueo"] is True, \
            "con movimientos de hoy y sin arqueo la caja pide el conteo"

        r = _arqueo(box["id"], {"1000": 1})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "cuadrada"
        res = _resumen(box["id"])
        assert res["needs_arqueo"] is False, \
            "tras registrar el arqueo de hoy ya no se pide"
        assert (res["arqueo_today"] or {}).get("status") == "cuadrada"
    finally:
        _cleanup()


def test_discrepancy_alerts_admins():
    _cleanup()
    db = _db()
    try:
        box = _mk_box()
        _mk_mov(box["id"], 1500, {"1000": 1, "500": 1})
        # contado 1000 vs sistema 1500 → FALTANTE de 500
        r = _arqueo(box["id"], {"1000": 1}, note="cierre")
        assert r.status_code == 200 and r.json()["status"] == "faltante", r.text

        n = db.notifications.find_one({
            "type": "cash_box_arqueo_diff",
            "recipient_user_id": "user_test_admin01",
            "message": {"$regex": MARK}}, {"_id": 0})
        assert n, "el faltante debe avisar a los admins (campana)"
        assert "FALTANTE" in n["message"] and "500.00 CUP" in n["message"], \
            n["message"]
        assert n["data"]["difference"] == -500.0

        # cuadrada → sin alerta nueva
        before = db.notifications.count_documents(
            {"type": "cash_box_arqueo_diff", "message": {"$regex": MARK}})
        r = _arqueo(box["id"], {"1000": 1, "500": 1})
        assert r.status_code == 200 and r.json()["status"] == "cuadrada"
        after = db.notifications.count_documents(
            {"type": "cash_box_arqueo_diff", "message": {"$regex": MARK}})
        assert after == before, "un arqueo cuadrado no genera alerta"

        # caja PERSONAL con sobrante → privada, sin alerta a admins
        pbox = _mk_box(scope="personal")
        _mk_mov(pbox["id"], 100, {"100": 1})
        r = _arqueo(pbox["id"], {"100": 2})
        assert r.status_code == 200 and r.json()["status"] == "sobrante"
        assert db.notifications.count_documents(
            {"type": "cash_box_arqueo_diff",
             "data.box_id": pbox["id"]}) == 0, \
            "las cajas personales no alertan a los admins"
    finally:
        _cleanup()


def test_daily_request_targets_pending_company_funds():
    _cleanup()
    db = _db()
    try:
        pending = _mk_box()          # empresa, con movimiento, SIN arqueo
        _mk_mov(pending["id"], 2000, {"1000": 2})
        done = _mk_box()             # empresa, con movimiento Y arqueo de hoy
        _mk_mov(done["id"], 1000, {"1000": 1})
        assert _arqueo(done["id"], {"1000": 1}).status_code == 200
        personal = _mk_box(scope="personal")  # personal, con movimiento
        _mk_mov(personal["id"], 500, {"500": 1})

        async def flow():
            from services.cash_box_arqueo import run_daily_arqueo_request
            return await run_daily_arqueo_request()

        n = _run(flow)
        assert n >= 1, "debe pedir el arqueo del fondo pendiente"

        note = db.notifications.find_one({
            "type": "cash_box_arqueo_due",
            "recipient_user_id": "user_test_admin01",
            "message": {"$regex": pending["name"]}}, {"_id": 0})
        assert note, "los admins reciben la petición de arqueo (campana)"
        assert done["name"] not in note["message"], \
            "una caja con arqueo de hoy no se vuelve a pedir"
        assert personal["name"] not in note["message"], \
            "las cajas personales no entran en la petición"
        assert "balance sistema 2,000.00 CUP" in note["message"], note["message"]
    finally:
        _cleanup()


def test_scheduler_job_registered():
    # H09 — ruta relativa al repo (la absoluta /app no existe en CI de GitHub)
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "scheduler.py") \
        .read_text(encoding="utf-8")
    assert src.count("daily_arqueo_request") >= 2, \
        "el job daily_arqueo_request debe estar definido y registrado"
    assert 'CronTrigger(hour=20, minute=0, timezone="America/Havana")' in src, \
        "el arqueo se pide al cierre del día (20:00 Cuba)"
