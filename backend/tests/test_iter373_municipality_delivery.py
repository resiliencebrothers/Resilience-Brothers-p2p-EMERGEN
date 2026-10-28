# iter373 — Marketplace home delivery: municipality-first flat rates (provinces, quotes, redeem, admin CRUD)
import os
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for ln in f:
            if ln.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = ln.split("=", 1)[1].strip()
BASE_URL = BASE_URL.rstrip("/")


def _env(key):
    with open("/app/backend/.env") as f:
        for ln in f:
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].strip().strip('"')


mdb = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]


def _s(tok):
    s = requests.Session()
    s.cookies.set("session_token", tok)
    return s


@pytest.fixture(scope="module")
def vip():
    return _s("muni_smoke_vip")


@pytest.fixture(scope="module")
def admin():
    return _s("muni_smoke_admin")


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


def _redeem(vip, **kw):
    return vip.post(f"{BASE_URL}/api/vip/redeem", json=kw)


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

    def test_compat_manual_review(self, vip, product):
        r = _redeem(vip, product_id=product, quantity=1,
                    delivery_address="Some unknown place 123 zzz",
                    receiver_phone="+5355555555")
        assert r.status_code == 200, r.text
        doc = mdb.redemptions.find_one({"id": r.json()["id"]}, {"_id": 0})
        assert doc["courier_fee_status"] == "manual_review"
        assert doc["courier_fee_usdt"] == 0

    def test_compat_detect_from_text(self, vip, product):
        r = _redeem(vip, product_id=product, quantity=1,
                    delivery_address="Calle 23, Vedado, La Habana",
                    receiver_phone="+5355555555")
        assert r.status_code == 200, r.text
        doc = mdb.redemptions.find_one({"id": r.json()["id"]}, {"_id": 0})
        assert doc["courier_fee_status"] == "charged"
        assert doc["courier_municipality"] == "Vedado"
        assert doc["courier_fee_usdt"] == 3.0

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
