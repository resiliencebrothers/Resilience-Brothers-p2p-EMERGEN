# iter373 — Marketplace home delivery: municipality-first flat rates (provinces, quotes, redeem, admin CRUD)
import os
import uuid
import pytest
import requests
from pymongo import MongoClient
# MUNI-Q01 (portabilidad) — usar los tokens canónicos que conftest siembra y
# re-verifica ANTES de cada test (`_autoseed_sessions`), en vez de tokens
# `muni_smoke_*` que ningún arnés creaba. Así la suite corre en cualquier
# entorno (local o CI) sin depender de sesiones sembradas a mano.
from conftest import VIP_TOKEN, ADMIN_TOKEN

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for ln in f:
            if ln.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = ln.split("=", 1)[1].strip()
BASE_URL = BASE_URL.rstrip("/")


def _env(key):
    # MUNI-Q01 (portabilidad) — primero el entorno del arnés (os.environ, que
    # conftest/CI definen); el fichero .env queda como APOYO opcional de
    # desarrollo, no requisito: su ausencia ya no rompe la suite (FileNotFound).
    val = os.environ.get(key)
    if val:
        return val
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for ln in f:
                if ln.startswith(key + "="):
                    return ln.split("=", 1)[1].strip().strip('"')
    return None


mdb = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]


def _s(tok):
    s = requests.Session()
    s.cookies.set("session_token", tok)
    return s


@pytest.fixture(scope="module")
def vip():
    return _s(VIP_TOKEN)


@pytest.fixture(scope="module")
def admin():
    return _s(ADMIN_TOKEN)


@pytest.fixture(scope="module")
def vedado(vip):
    rows = vip.get(f"{BASE_URL}/api/courier/municipality-rates",
                   params={"province": "La Habana"}).json()
    return next(r for r in rows if r["municipality"] == "Vedado")


@pytest.fixture(scope="module")
def product():
    """Own-inventory TEST_ product, price 300 USDT, stock 50."""
    pid = f"TEST_muni_{uuid.uuid4().hex[:8]}"
    mdb.products.insert_one({
        "id": pid, "name": f"TEST_MuniProd_{pid[-4:]}", "description": "t",
        "image_url": "", "price_usd": 300.0, "price_usdt": 300.0, "cost_usd": 100.0,
        "stock": 50.0, "category": "test", "is_active": True, "unit": "unidad",
        "owner_id": None, "owner_name": "", "approval_status": "approved",
        "created_at": "2026-01-01T00:00:00+00:00"})
    yield pid
    mdb.products.delete_one({"id": pid})


def _bal():
    u = mdb.users.find_one({"user_id": "user_test_vip01"}, {"_id": 0})
    return float((u.get("vip_balances") or {}).get("USDT", 0))


@pytest.fixture(scope="module", autouse=True)
def _fund_vip():
    """Repetibilidad — los tests de compra GASTAN saldo USDT real de forma
    irreversible, así que en una 2ª corrida el saldo se agota y fallan. Fijamos
    un saldo conocido y amplio antes del módulo y restauramos el original al
    final, dejando la BD como estaba."""
    u = mdb.users.find_one({"user_id": "user_test_vip01"},
                           {"_id": 0, "vip_balances": 1}) or {}
    prev = (u.get("vip_balances") or {}).get("USDT", 0)
    mdb.users.update_one({"user_id": "user_test_vip01"},
                         {"$set": {"vip_balances.USDT": 100000.0}})
    yield
    mdb.users.update_one({"user_id": "user_test_vip01"},
                         {"$set": {"vip_balances.USDT": prev}})


def _redeem(vip, **kw):
    return vip.post(f"{BASE_URL}/api/vip/redeem", json=kw)


@pytest.fixture(scope="module")
def homonym(admin):
    """MUNI-02-R2 — dos municipios ACTIVOS con el MISMO nombre normalizado en
    provincias distintas y precios distintos. El nombre, SIN provincia, es
    AMBIGUO y debe rechazarse antes de cobrar."""
    name = f"TEST_Ambig_{uuid.uuid4().hex[:4]}"
    a = admin.post(f"{BASE_URL}/api/admin/courier/municipality-rates",
                   json={"municipality": name, "province": "TEST_AmbigA",
                         "price_usdt": 4})
    b = admin.post(f"{BASE_URL}/api/admin/courier/municipality-rates",
                   json={"municipality": name, "province": "TEST_AmbigB",
                         "price_usdt": 8})
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    ids = [a.json()["id"], b.json()["id"]]
    yield {"name": name, "id_a": ids[0], "id_b": ids[1]}
    for mid in ids:
        mdb.courier_municipality_rates.delete_one({"id": mid})


# --- Public (auth) listing endpoints
class TestListing:
    def test_provinces_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/courier/delivery-provinces")
        assert r.status_code == 401

    def test_provinces(self, vip):
        r = vip.get(f"{BASE_URL}/api/courier/delivery-provinces")
        assert r.status_code == 200
        assert "La Habana" in r.json()

    def test_rates_la_habana(self, vip):
        r = vip.get(f"{BASE_URL}/api/courier/municipality-rates",
                    params={"province": "La Habana"})
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 15
        for x in rows:
            assert set(x) == {"id", "municipality", "province", "price_usdt"}
            assert x["province"] == "La Habana"


# --- Quote endpoint
class TestQuote:
    def test_vedado_charged(self, vip, vedado):
        r = vip.get(f"{BASE_URL}/api/vip/courier-municipality-quote",
                    params={"municipality": vedado["id"], "currency": "USDT", "amount": 390})
        d = r.json()
        assert r.status_code == 200 and d["matched"] is True
        assert d["free"] is False and d["fee_usdt"] == 3.0
        assert d["municipality"] == "Vedado" and d["province"] == "La Habana"

    def test_vedado_free(self, vip, vedado):
        d = vip.get(f"{BASE_URL}/api/vip/courier-municipality-quote",
                    params={"municipality": vedado["id"], "currency": "USDT", "amount": 1800}).json()
        assert d["matched"] is True and d["free"] is True and d["fee_usdt"] == 0.0

    def test_unknown(self, vip):
        d = vip.get(f"{BASE_URL}/api/vip/courier-municipality-quote",
                    params={"municipality": "muni_nope_xyz", "currency": "USDT", "amount": 390}).json()
        assert d == {"matched": False}


# --- Redeem
class TestRedeem:
    def test_charged_by_municipality(self, vip, product, vedado):
        b0 = _bal()
        r = _redeem(vip, product_id=product, quantity=1, delivery_address="Calle X #1",
                    courier_municipality=vedado["id"], courier_province="La Habana",
                    expected_courier_fee_usdt=3.0, receiver_name="T", receiver_phone="+5355555555")
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        doc = mdb.redemptions.find_one({"id": rid}, {"_id": 0})
        assert doc["courier_fee_status"] == "charged"
        assert doc["courier_municipality"] == "Vedado"
        assert doc["courier_municipality_id"] == vedado["id"]
        assert doc["courier_province"] == "La Habana"
        assert doc["courier_price_usdt_snapshot"] == 3.0
        assert doc["courier_fee_usdt"] == 3.0
        assert abs((b0 - _bal()) - 303.0) < 0.01

    def test_free_over_threshold(self, vip, product, vedado):
        r = _redeem(vip, product_id=product, quantity=4, delivery_address="Calle X #5",
                    courier_municipality=vedado["id"], courier_province="La Habana",
                    receiver_phone="+5355555555", expected_courier_fee_usdt=0)
        assert r.status_code == 200, r.text
        doc = mdb.redemptions.find_one({"id": r.json()["id"]}, {"_id": 0})
        assert doc["courier_fee_status"] == "free" and doc["courier_fee_usdt"] == 0
        assert doc["courier_municipality"] == "Vedado"
        assert doc["courier_province"] == "La Habana"

    def test_missing_municipality_rejected(self, vip, product):
        """MUNI-02-R — SIN municipio explícito la compra a domicilio se RECHAZA
        antes de cualquier efecto económico: ya no cae a revisión manual ni a
        detección silenciosa por texto. El saldo queda intacto."""
        b0 = _bal()
        r = _redeem(vip, product_id=product, quantity=1,
                    delivery_address="Some unknown place 123 zzz",
                    receiver_phone="+5355555555", expected_courier_fee_usdt=0)
        assert r.status_code == 400, r.text
        assert r.json()["detail"].startswith("COURIER_NO_MUNICIPALITY")
        assert abs(_bal() - b0) < 0.001

    def test_text_only_without_municipality_rejected(self, vip, product):
        """MUNI-02-R — aunque el municipio aparezca en el TEXTO de la dirección,
        omitir el municipio EXPLÍCITO ya no abre un contrato de cobro: se exige
        el destino resuelto por el servidor, no la detección por texto."""
        b0 = _bal()
        r = _redeem(vip, product_id=product, quantity=1,
                    delivery_address="Calle 23, Vedado, La Habana",
                    receiver_phone="+5355555555", expected_courier_fee_usdt=3.0)
        assert r.status_code == 400, r.text
        assert r.json()["detail"].startswith("COURIER_NO_MUNICIPALITY")
        assert abs(_bal() - b0) < 0.001

    def test_missing_expected_fee_rejected(self, vip, product, vedado):
        """MUNI-04-R — la aceptación del importe de mensajería es OBLIGATORIA
        para entrega a domicilio: omitir expected_courier_fee_usdt se rechaza
        ANTES de cobrar; el saldo queda intacto."""
        b0 = _bal()
        r = _redeem(vip, product_id=product, quantity=1,
                    delivery_address="Calle 23 #456, Vedado",
                    receiver_phone="+5355555555",
                    courier_municipality=vedado["id"], courier_province="La Habana")
        assert r.status_code == 400, r.text
        assert r.json()["detail"].startswith("COURIER_FEE_UNCONFIRMED")
        assert abs(_bal() - b0) < 0.001

    def test_province_mismatch_by_id_rejected(self, vip, product, vedado):
        """MUNI-02-R — un id de municipio VÁLIDO con una provincia que NO
        coincide no se reinterpreta a la tarifa de otro territorio: se rechaza
        como sin cobertura, antes de cobrar. El saldo queda intacto."""
        b0 = _bal()
        r = _redeem(vip, product_id=product, quantity=1,
                    delivery_address="Calle 23 #456, Vedado",
                    receiver_phone="+5355555555",
                    courier_municipality=vedado["id"],
                    courier_province="TEST_Otra Provincia",
                    expected_courier_fee_usdt=3.0)
        assert r.status_code == 400, r.text
        assert r.json()["detail"].startswith("COURIER_NO_COVERAGE")
        assert abs(_bal() - b0) < 0.001

    def test_fee_changed_409(self, vip, product, vedado):
        b0 = _bal()
        r = _redeem(vip, product_id=product, quantity=1,
                    delivery_address="Calle 23 #456, Vedado",
                    receiver_phone="+5355555555",
                    courier_municipality=vedado["id"], expected_courier_fee_usdt=5.0)
        assert r.status_code == 409
        assert r.json()["detail"].startswith("COURIER_FEE_CHANGED")
        assert abs(_bal() - b0) < 0.001

    def test_explicit_no_coverage_rejected(self, vip, product):
        """MUNI-02 — un municipio EXPLÍCITO sin cobertura NO se procesa en
        silencio: se rechaza ANTES de cobrar y el saldo queda intacto."""
        b0 = _bal()
        r = _redeem(vip, product_id=product, quantity=1,
                    delivery_address="Calle sin cobertura #123",
                    receiver_phone="+5355555555",
                    courier_municipality="muni_nope_xyz",
                    courier_province="La Habana")
        assert r.status_code == 400, r.text
        assert r.json()["detail"].startswith("COURIER_NO_COVERAGE")
        assert abs(_bal() - b0) < 0.001

    def test_phone_required_for_delivery(self, vip, product, vedado):
        """MUNI-06 — entrega a domicilio exige teléfono de contacto válido."""
        b0 = _bal()
        r = _redeem(vip, product_id=product, quantity=1,
                    delivery_address="Calle 23 #456, Vedado",
                    courier_municipality=vedado["id"], courier_province="La Habana")
        assert r.status_code == 400, r.text
        assert abs(_bal() - b0) < 0.001

    def test_address_required_for_delivery(self, vip, product, vedado):
        """MUNI-06 — dirección demasiado corta se rechaza (tras recortar)."""
        r = _redeem(vip, product_id=product, quantity=1, delivery_address="  x  ",
                    receiver_phone="+5355555555",
                    courier_municipality=vedado["id"], courier_province="La Habana")
        assert r.status_code == 400, r.text

    def test_ambiguous_name_without_province_rejected(self, vip, product, homonym):
        """MUNI-02-R2 — enviar el NOMBRE homónimo sin provincia NO elige un
        territorio al azar: se rechaza (ambigüedad) ANTES de cobrar; el saldo
        queda intacto. Sin provincia, con cadena vacía y con espacios, igual."""
        for prov in (None, "", "   "):
            b0 = _bal()
            kw = dict(product_id=product, quantity=1,
                      delivery_address="Calle Ambigua #10",
                      receiver_phone="+5355555555",
                      courier_municipality=homonym["name"],
                      expected_courier_fee_usdt=4.0)
            if prov is not None:
                kw["courier_province"] = prov
            r = _redeem(vip, **kw)
            assert r.status_code == 400, (prov, r.text)
            assert r.json()["detail"].startswith(
                "COURIER_AMBIGUOUS_MUNICIPALITY"), (prov, r.text)
            assert abs(_bal() - b0) < 0.001

    def test_ambiguous_name_with_province_resolves(self, vip, product, homonym):
        """MUNI-02-R2 — el MISMO nombre homónimo CON su provincia resuelve a la
        tarifa de ESE territorio (nunca la primera global): cobro correcto."""
        b0 = _bal()
        r = _redeem(vip, product_id=product, quantity=1,
                    delivery_address="Calle Ambigua #20",
                    receiver_phone="+5355555555",
                    courier_municipality=homonym["name"],
                    courier_province="TEST_AmbigB",
                    expected_courier_fee_usdt=8.0)
        assert r.status_code == 200, r.text
        doc = mdb.redemptions.find_one({"id": r.json()["id"]}, {"_id": 0})
        assert doc["courier_province"] == "TEST_AmbigB"
        assert doc["courier_fee_usdt"] == 8.0
        assert abs((b0 - _bal()) - (300.0 + 8.0)) < 0.01



# --- Admin CRUD with provinces
class TestAdmin:
    created = []

    @classmethod
    def teardown_class(cls):
        for mid in cls.created:
            mdb.courier_municipality_rates.delete_one({"id": mid})

    def test_create_new_province(self, admin, vip):
        name = f"TEST_SantaClara_{uuid.uuid4().hex[:4]}"
        r = admin.post(f"{BASE_URL}/api/admin/courier/municipality-rates",
                       json={"municipality": name, "province": "TEST_Villa Clara", "price_usdt": 6})
        assert r.status_code == 200, r.text
        d = r.json()
        self.created.append(d["id"])
        assert d["province"] == "TEST_Villa Clara" and d["price_usdt"] == 6
        assert "TEST_Villa Clara" in vip.get(f"{BASE_URL}/api/courier/delivery-provinces").json()
        # same name, other province -> OK
        r2 = admin.post(f"{BASE_URL}/api/admin/courier/municipality-rates",
                        json={"municipality": name, "province": "TEST_Matanzas", "price_usdt": 4})
        assert r2.status_code == 200, r2.text
        self.created.append(r2.json()["id"])
        # same name, same province -> 409
        r3 = admin.post(f"{BASE_URL}/api/admin/courier/municipality-rates",
                        json={"municipality": name.upper(), "province": "test_villa clara", "price_usdt": 4})
        assert r3.status_code == 409

    def test_vip_forbidden(self, vip):
        r = vip.post(f"{BASE_URL}/api/admin/courier/municipality-rates",
                     json={"municipality": "TEST_x", "province": "TEST_P", "price_usdt": 1})
        assert r.status_code == 403

    def test_province_disambiguates_homonym(self, admin, vip):
        """Mismo nombre de municipio en 2 provincias con precios distintos:
        la cotización por NOMBRE + province devuelve la tarifa correcta."""
        name = f"TEST_Homonimo_{uuid.uuid4().hex[:4]}"
        a = admin.post(f"{BASE_URL}/api/admin/courier/municipality-rates",
                       json={"municipality": name, "province": "TEST_ProvA", "price_usdt": 6})
        b = admin.post(f"{BASE_URL}/api/admin/courier/municipality-rates",
                       json={"municipality": name, "province": "TEST_ProvB", "price_usdt": 9})
        assert a.status_code == 200 and b.status_code == 200
        self.created += [a.json()["id"], b.json()["id"]]
        qa = vip.get(f"{BASE_URL}/api/vip/courier-municipality-quote",
                     params={"municipality": name, "province": "TEST_ProvA",
                             "currency": "USDT", "amount": 390}).json()
        qb = vip.get(f"{BASE_URL}/api/vip/courier-municipality-quote",
                     params={"municipality": name, "province": "TEST_ProvB",
                             "currency": "USDT", "amount": 390}).json()
        assert qa["matched"] and qa["fee_usdt"] == 6.0 and qa["province"] == "TEST_ProvA"
        assert qb["matched"] and qb["fee_usdt"] == 9.0 and qb["province"] == "TEST_ProvB"

    def test_regex_special_chars(self, admin):
        r = admin.post(f"{BASE_URL}/api/admin/courier/municipality-rates",
                       json={"municipality": "TEST_Bad (name", "province": "TEST_P", "price_usdt": 1})
        if r.status_code == 200:
            self.created.append(r.json()["id"])
        assert r.status_code in (200, 409), f"regex special char -> {r.status_code}"
