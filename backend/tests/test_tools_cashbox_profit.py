"""Backend tests for Tools: Caja Negocio + Reporte .xlsx + Profit Scenarios.

Scope matches review_request iteration_100.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

VIP_TOKEN = "test_session_vip_X"
EMP_TOKEN = "test_session_empresa_e2e_X"


def _c(token: str) -> requests.Session:
    s = requests.Session()
    s.cookies.set("session_token", token)
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def vip():
    return _c(VIP_TOKEN)


@pytest.fixture(scope="module")
def emp():
    return _c(EMP_TOKEN)


@pytest.fixture(scope="module")
def created_store(emp):
    """Crear una tienda real para la empresa de prueba."""
    r = emp.post(f"{API}/company/stores", json={
        "name": f"TEST_QA_{uuid.uuid4().hex[:6]}",
        "address": "Calle 1 e/ 2 y 3",
        "municipality": "Habana", "province": "La Habana",
        "phone": "555", "hours": "9-5", "active": True,
    })
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    yield sid
    # cleanup not critical


# ================ Caja Negocio ================

class TestCajaNegocio:
    def test_empresa_crea_caja_negocio(self, emp):
        r = emp.post(f"{API}/cashbox/boxes", json={
            "name": f"TEST_CajaNeg_{uuid.uuid4().hex[:6]}", "scope": "negocio"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["scope"] == "negocio"
        assert d["company_id"]  # non-empty
        assert d["store_id"] in (None, "")
        # cleanup
        emp.delete(f"{API}/cashbox/boxes/{d['id']}")

    def test_empresa_crea_caja_negocio_con_tienda(self, emp, created_store):
        r = emp.post(f"{API}/cashbox/boxes", json={
            "name": f"TEST_CajaNegT_{uuid.uuid4().hex[:6]}",
            "scope": "negocio", "store_id": created_store})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["scope"] == "negocio"
        assert d["store_id"] == created_store
        assert d.get("store_name")
        emp.delete(f"{API}/cashbox/boxes/{d['id']}")

    def test_empresa_store_id_invalido(self, emp):
        r = emp.post(f"{API}/cashbox/boxes", json={
            "name": "TEST_BadStore", "scope": "negocio",
            "store_id": "store_does_not_exist_xx"})
        assert r.status_code == 400, r.text

    def test_empresa_list_includes_negocio(self, emp):
        # create one
        r = emp.post(f"{API}/cashbox/boxes", json={
            "name": f"TEST_ListNeg_{uuid.uuid4().hex[:6]}", "scope": "negocio"})
        assert r.status_code == 200
        bid = r.json()["id"]
        try:
            lst = emp.get(f"{API}/cashbox/boxes").json()
            assert any(b["id"] == bid and b["scope"] == "negocio" for b in lst)
        finally:
            emp.delete(f"{API}/cashbox/boxes/{bid}")

    def test_vip_no_puede_crear_negocio(self, vip):
        r = vip.post(f"{API}/cashbox/boxes", json={
            "name": "TEST_VipNeg", "scope": "negocio"})
        assert r.status_code == 403, r.text

    def test_vip_list_no_incluye_negocio(self, vip):
        lst = vip.get(f"{API}/cashbox/boxes").json()
        assert all(b.get("scope") != "negocio" for b in lst)


# ================ Reporte Excel ================

class TestReporteXlsx:
    @pytest.fixture(scope="class")
    def emp_box(self, emp):
        r = emp.post(f"{API}/cashbox/boxes", json={
            "name": f"TEST_XlsxBox_{uuid.uuid4().hex[:6]}", "scope": "negocio"})
        assert r.status_code == 200
        bid = r.json()["id"]
        yield bid
        emp.delete(f"{API}/cashbox/boxes/{bid}")

    def test_reporte_xlsx_ok(self, emp, emp_box):
        r = emp.get(f"{API}/cashbox/boxes/{emp_box}/reporte.xlsx",
                    params={"fund": "CUP", "month": "2026-10"})
        assert r.status_code == 200, r.text
        assert "spreadsheetml.sheet" in r.headers.get("content-type", "")
        assert len(r.content) > 100

    def test_reporte_xlsx_mes_invalido(self, emp, emp_box):
        r = emp.get(f"{API}/cashbox/boxes/{emp_box}/reporte.xlsx",
                    params={"fund": "CUP", "month": "2026-13"})
        assert r.status_code == 400

    def test_reporte_xlsx_fondo_invalido(self, emp, emp_box):
        r = emp.get(f"{API}/cashbox/boxes/{emp_box}/reporte.xlsx",
                    params={"fund": "EUR", "month": "2026-10"})
        assert r.status_code == 400


# ================ Profit Scenarios ================

class TestProfitScenarios:
    def test_crud_y_privacidad(self, vip, emp):
        # VIP create
        r = vip.post(f"{API}/profit/scenarios", json={
            "name": f"TEST_vip_{uuid.uuid4().hex[:4]}",
            "calc": {"a": 1, "b": 2}})
        assert r.status_code == 200, r.text
        sc = r.json()
        sid = sc["id"]
        assert sc["calc"] == {"a": 1, "b": 2}

        # List includes it
        lst = vip.get(f"{API}/profit/scenarios").json()
        assert any(x["id"] == sid for x in lst)

        # Rename
        r = vip.put(f"{API}/profit/scenarios/{sid}",
                    json={"name": "TEST_vip_renamed"})
        assert r.status_code == 200
        assert r.json()["name"] == "TEST_vip_renamed"

        # Update calc
        r = vip.put(f"{API}/profit/scenarios/{sid}",
                    json={"calc": {"a": 10}})
        assert r.status_code == 200
        assert r.json()["calc"] == {"a": 10}

        # Privacy: empresa should NOT see vip's scenario
        emp_lst = emp.get(f"{API}/profit/scenarios").json()
        assert all(x["id"] != sid for x in emp_lst)

        # Empresa creates its own
        r = emp.post(f"{API}/profit/scenarios", json={
            "name": "TEST_emp_1", "calc": {"x": 9}})
        assert r.status_code == 200
        eid = r.json()["id"]

        # VIP should not see empresa's scenario
        vlst = vip.get(f"{API}/profit/scenarios").json()
        assert all(x["id"] != eid for x in vlst)

        # Delete both
        r = vip.delete(f"{API}/profit/scenarios/{sid}")
        assert r.status_code == 200
        r = emp.delete(f"{API}/profit/scenarios/{eid}")
        assert r.status_code == 200

        # Deleted → 404 on PUT
        r = vip.put(f"{API}/profit/scenarios/{sid}", json={"name": "x"})
        assert r.status_code == 404
