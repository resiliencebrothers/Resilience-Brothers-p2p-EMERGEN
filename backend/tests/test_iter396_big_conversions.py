"""iter396 — Conversiones en historiales grandes (revisión 6d53890, hallazgo 1).

Antes `_fetch_conversions` leía 5.000 por fuente SIN orden y filtraba la moneda
en memoria: con >5.000 operaciones podía descartar conversiones recientes o de
la moneda buscada. Ahora el filtro de moneda va EN LA BASE DE DATOS y cada
fuente se lee ordenada por fecha desc antes del límite.

Caso: 5.016 conversiones USDT→CUP (recientes) + 4 ZZZT→USDT (antiguas). Buscar
'ZZZT' debe devolver las 4 aunque queden "detrás" de 5.000 operaciones nuevas.
"""
import asyncio
import os

from pymongo import MongoClient

from services.transactions import _fetch_conversions

MARK = "iter396_bigconv"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _conv(i, from_code, to_code, created_at):
    return {
        "id": f"{MARK}_{from_code}_{i}", "test_marker": MARK, "status": "applied",
        "user_name": "QA Big", "user_email": "qa.big@example.com",
        "created_at": created_at, "from_code": from_code, "to_code": to_code,
        "amount_from": 1.0, "amount_to": 1.0, "rate": 1.0, "usdt_fee": 0.01,
        "amount_from_usdt": 1.0, "kind": "convert",
    }


def setup_module(_):
    db = _db()
    noise = [_conv(i, "USDT", "CUP", f"2026-07-01T00:{i % 60:02d}:00+00:00")
             for i in range(5016)]
    rare = [_conv(i, "ZZZT", "USDT", f"2020-01-0{i + 1}T00:00:00+00:00")
            for i in range(4)]
    db.conversions.insert_many(noise + rare)


def teardown_module(_):
    _db().conversions.delete_many({"test_marker": MARK})


def test_rare_currency_not_dropped_beyond_cap():
    items = asyncio.run(_fetch_conversions({}, "ZZZT", None))
    mine = [it for it in items if it.get("ref_id", "").startswith(MARK)
            or it.get("from_code") == "ZZZT"]
    # Las 4 conversiones ZZZT (antiguas) se recuperan pese a los 5.016 ruidos nuevos.
    zzzt = [it for it in items if it.get("from_code") == "ZZZT" and it.get("ref_id", "").startswith(MARK)]
    assert len(zzzt) == 4, f"esperaba 4 ZZZT, obtuve {len(zzzt)} (total {len(mine)})"
    # Ninguna USDT→CUP se cuela al filtrar por ZZZT (filtro en BD).
    assert all(it.get("to_code") != "CUP" for it in zzzt)


def test_results_sorted_desc_by_date():
    items = asyncio.run(_fetch_conversions({}, "USDT", None))
    mine = [it.get("created_at", "") for it in items
            if it.get("ref_id", "").startswith(MARK)]
    assert mine == sorted(mine, reverse=True)
