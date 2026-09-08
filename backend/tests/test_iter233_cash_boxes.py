"""iter233 — Caja de Efectivo (Caja En Vivo integrada).

Cubre:
- CRUD de cajas: personales (privadas por dueño) y de empresa (solo staff).
- Privacidad: un usuario NO ve ni toca las cajas personales de otro (403/lista).
- Cliente normal no crea cajas de empresa (403) ni las ve.
- Saldo inicial con desglose (validación de suma) + balance = inicial + E − S.
- Movimientos: crear/editar/eliminar, desglose inválido → 400.
- Resumen: entradas/salidas del mes, neto y control físico por denominación.
- Arqueo: cuadrada y con diferencia (sobrante/faltante).
- Reporte mensual por días.
- Export Excel (magic bytes PK).
- Borrar caja con movimientos → 409; sin movimientos → ok.
"""
import os

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER233TEST"


def _h(tok):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _mkbox(tok, name, scope="personal"):
    return requests.post(f"{API}/cashbox/boxes", headers=_h(tok),
                         json={"name": name, "scope": scope})


class TestCashBoxes:
    def teardown_method(self, _):
        db = _db()
        ids = [b["id"] for b in db.cash_boxes.find({"name": {"$regex": f"^{MARK}"}})]
        db.cash_boxes.delete_many({"id": {"$in": ids}})
        db.cash_box_movements.delete_many({"box_id": {"$in": ids}})
        db.cash_box_arqueos.delete_many({"box_id": {"$in": ids}})

    # ------------------------------------------------ cajas y permisos

    def test_create_and_list_personal_box(self):
        r = _mkbox(NORMAL_TOKEN, f"{MARK} Casa")
        assert r.status_code == 200, r.text
        assert r.json()["scope"] == "personal"
        boxes = requests.get(f"{API}/cashbox/boxes",
                             headers=_h(NORMAL_TOKEN)).json()
        assert any(b["id"] == r.json()["id"] for b in boxes)
        assert boxes[0].get("balances") is not None

    def test_personal_box_private_between_users(self):
        box = _mkbox(NORMAL_TOKEN, f"{MARK} Privada").json()
        vip_boxes = requests.get(f"{API}/cashbox/boxes", headers=_h(VIP_TOKEN)).json()
        assert not any(b["id"] == box["id"] for b in vip_boxes)
        r = requests.get(f"{API}/cashbox/boxes/{box['id']}/resumen",
                         params={"fund": "CUP"}, headers=_h(VIP_TOKEN))
        assert r.status_code == 403
        r2 = requests.post(f"{API}/cashbox/boxes/{box['id']}/movimientos",
                           headers=_h(VIP_TOKEN),
                           json={"fund": "CUP", "type": "entrada",
                                 "amount": 10, "concept": "intruso"})
        assert r2.status_code == 403

    def test_empresa_box_staff_only(self):
        r = _mkbox(NORMAL_TOKEN, f"{MARK} EmpresaNo", scope="empresa")
        assert r.status_code == 403
        box = _mkbox(ADMIN_TOKEN, f"{MARK} Almacén", scope="empresa").json()
        # admin la ve; cliente normal no
        admin_boxes = requests.get(f"{API}/cashbox/boxes", headers=_h(ADMIN_TOKEN)).json()
        assert any(b["id"] == box["id"] for b in admin_boxes)
        normal_boxes = requests.get(f"{API}/cashbox/boxes", headers=_h(NORMAL_TOKEN)).json()
        assert not any(b["id"] == box["id"] for b in normal_boxes)

    def test_unauthenticated_401(self):
        assert requests.get(f"{API}/cashbox/boxes").status_code == 401

    # -------------------------------------------- inicial y movimientos

    def test_initial_movements_and_balance_math(self):
        box = _mkbox(NORMAL_TOKEN, f"{MARK} Mate").json()
        # inicial 1500 = 1×1000 + 1×500
        r = requests.post(f"{API}/cashbox/boxes/{box['id']}/inicial",
                          headers=_h(NORMAL_TOKEN),
                          json={"fund": "CUP", "amount": 1500,
                                "denominations": {"1000": 1, "500": 1}})
        assert r.status_code == 200, r.text
        # entrada 700 (500+200) + salida 300
        requests.post(f"{API}/cashbox/boxes/{box['id']}/movimientos",
                      headers=_h(NORMAL_TOKEN),
                      json={"fund": "CUP", "type": "entrada", "amount": 700,
                            "concept": "venta", "responsible": "Ana",
                            "denominations": {"500": 1, "200": 1}})
        requests.post(f"{API}/cashbox/boxes/{box['id']}/movimientos",
                      headers=_h(NORMAL_TOKEN),
                      json={"fund": "CUP", "type": "salida", "amount": 300,
                            "concept": "compra"})
        res = requests.get(f"{API}/cashbox/boxes/{box['id']}/resumen",
                           params={"fund": "CUP"},
                           headers=_h(NORMAL_TOKEN)).json()
        assert res["balance"] == 1900.0        # 1500 + 700 − 300
        assert res["entradas_total"] == 700.0
        assert res["salidas_total"] == 300.0
        assert res["entradas_mes"] == 700.0
        assert res["neto_mes"] == 400.0
        # control físico: 1000×1, 500×2 (1 inicial + 1 entrada), 200×1
        d = {r["denom"]: r["qty"] for r in res["denominaciones"]}
        assert d[1000] == 1 and d[500] == 2 and d[200] == 1
        # el fondo USD queda intacto
        usd = requests.get(f"{API}/cashbox/boxes/{box['id']}/resumen",
                           params={"fund": "USD"},
                           headers=_h(NORMAL_TOKEN)).json()
        assert usd["balance"] == 0.0

    def test_denomination_mismatch_400(self):
        box = _mkbox(NORMAL_TOKEN, f"{MARK} Val").json()
        r = requests.post(f"{API}/cashbox/boxes/{box['id']}/movimientos",
                          headers=_h(NORMAL_TOKEN),
                          json={"fund": "CUP", "type": "entrada", "amount": 100,
                                "concept": "x", "denominations": {"50": 1}})
        assert r.status_code == 400
        # denominación inexistente en USD
        r2 = requests.post(f"{API}/cashbox/boxes/{box['id']}/movimientos",
                           headers=_h(NORMAL_TOKEN),
                           json={"fund": "USD", "type": "entrada", "amount": 200,
                                 "concept": "x", "denominations": {"200": 1}})
        assert r2.status_code == 400

    def test_edit_and_delete_movement(self):
        box = _mkbox(NORMAL_TOKEN, f"{MARK} Edit").json()
        m = requests.post(f"{API}/cashbox/boxes/{box['id']}/movimientos",
                          headers=_h(NORMAL_TOKEN),
                          json={"fund": "CUP", "type": "entrada", "amount": 100,
                                "concept": "inicial",
                                "denominations": {"100": 1}}).json()
        r = requests.put(f"{API}/cashbox/boxes/{box['id']}/movimientos/{m['id']}",
                         headers=_h(NORMAL_TOKEN),
                         json={"amount": 250, "concept": "corregido"})
        assert r.status_code == 200
        upd = r.json()
        assert upd["amount"] == 250 and upd["concept"] == "corregido"
        assert upd["denominations"] is None    # desglose viejo ya no cuadra
        r2 = requests.delete(
            f"{API}/cashbox/boxes/{box['id']}/movimientos/{m['id']}",
            headers=_h(NORMAL_TOKEN))
        assert r2.status_code == 200
        movs = requests.get(f"{API}/cashbox/boxes/{box['id']}/movimientos",
                            params={"fund": "CUP"},
                            headers=_h(NORMAL_TOKEN)).json()
        assert movs == []

    # ------------------------------------------------------------ arqueo

    def test_arqueo_squared_and_difference(self):
        box = _mkbox(NORMAL_TOKEN, f"{MARK} Arq").json()
        requests.post(f"{API}/cashbox/boxes/{box['id']}/inicial",
                      headers=_h(NORMAL_TOKEN),
                      json={"fund": "USD", "amount": 120})
        # contado exacto: 100+20 = 120 → cuadrada
        r = requests.post(f"{API}/cashbox/boxes/{box['id']}/arqueos",
                          headers=_h(NORMAL_TOKEN),
                          json={"fund": "USD", "counted": {"100": 1, "20": 1}})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "cuadrada"
        assert r.json()["difference"] == 0
        # contado 100 → faltante de 20
        r2 = requests.post(f"{API}/cashbox/boxes/{box['id']}/arqueos",
                           headers=_h(NORMAL_TOKEN),
                           json={"fund": "USD", "counted": {"100": 1},
                                 "note": "falta un billete"})
        assert r2.json()["status"] == "faltante"
        assert r2.json()["difference"] == -20.0
        hist = requests.get(f"{API}/cashbox/boxes/{box['id']}/arqueos",
                            params={"fund": "USD"},
                            headers=_h(NORMAL_TOKEN)).json()
        assert len(hist) == 2

    # ----------------------------------------------------------- reporte

    def test_monthly_report(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        box = _mkbox(NORMAL_TOKEN, f"{MARK} Rep").json()
        requests.post(f"{API}/cashbox/boxes/{box['id']}/movimientos",
                      headers=_h(NORMAL_TOKEN),
                      json={"fund": "CUP", "type": "entrada", "amount": 500,
                            "concept": "venta"})
        requests.post(f"{API}/cashbox/boxes/{box['id']}/movimientos",
                      headers=_h(NORMAL_TOKEN),
                      json={"fund": "CUP", "type": "salida", "amount": 200,
                            "concept": "gasto"})
        month = datetime.now(ZoneInfo("America/Havana")).strftime("%Y-%m")
        rep = requests.get(f"{API}/cashbox/boxes/{box['id']}/reporte",
                           params={"fund": "CUP", "month": month},
                           headers=_h(NORMAL_TOKEN)).json()
        assert rep["total_entradas"] == 500.0
        assert rep["total_salidas"] == 200.0
        assert rep["neto"] == 300.0
        assert len(rep["days"]) == 1
        # mes vacío
        rep0 = requests.get(f"{API}/cashbox/boxes/{box['id']}/reporte",
                            params={"fund": "CUP", "month": "2020-01"},
                            headers=_h(NORMAL_TOKEN)).json()
        assert rep0["days"] == []
        # mes inválido
        assert requests.get(f"{API}/cashbox/boxes/{box['id']}/reporte",
                            params={"fund": "CUP", "month": "x"},
                            headers=_h(NORMAL_TOKEN)).status_code == 400

    # ------------------------------------------------------------ export

    def test_export_xlsx(self):
        box = _mkbox(NORMAL_TOKEN, f"{MARK} Xls").json()
        requests.post(f"{API}/cashbox/boxes/{box['id']}/movimientos",
                      headers=_h(NORMAL_TOKEN),
                      json={"fund": "CUP", "type": "entrada", "amount": 100,
                            "concept": "venta"})
        r = requests.get(f"{API}/cashbox/boxes/{box['id']}/export.xlsx",
                         params={"fund": "CUP"}, headers=_h(NORMAL_TOKEN))
        assert r.status_code == 200
        assert r.content[:2] == b"PK"
        assert "caja_CUP" in r.headers["content-disposition"]

    # ------------------------------------------------------------ borrar

    def test_delete_box_guard(self):
        box = _mkbox(NORMAL_TOKEN, f"{MARK} Del").json()
        requests.post(f"{API}/cashbox/boxes/{box['id']}/movimientos",
                      headers=_h(NORMAL_TOKEN),
                      json={"fund": "CUP", "type": "entrada", "amount": 10,
                            "concept": "x"})
        r = requests.delete(f"{API}/cashbox/boxes/{box['id']}",
                            headers=_h(NORMAL_TOKEN))
        assert r.status_code == 409
        empty = _mkbox(NORMAL_TOKEN, f"{MARK} Del2").json()
        r2 = requests.delete(f"{API}/cashbox/boxes/{empty['id']}",
                             headers=_h(NORMAL_TOKEN))
        assert r2.status_code == 200
