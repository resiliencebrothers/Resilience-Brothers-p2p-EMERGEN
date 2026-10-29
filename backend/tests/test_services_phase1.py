# Services Phase-1: company CRUD lifecycle, admin moderation, categories, public catalog
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
EMP = {"session_token": "svc_smoke_empresa"}
ADM = {"session_token": "svc_smoke_admin"}
VIP = {"session_token": "muni_smoke_vip"}

created = []


def _payload(**kw):
    p = {"title": f"TEST_svc_{uuid.uuid4().hex[:6]}", "category": "limpieza",
         "modality": "domicilio", "pricing_type": "fixed", "price_usdt": 25,
         "availability": [{"day": 0, "start": "09:00", "end": "12:00"}],
         "payment_methods": ["balance"], "coverage_zone": "Vedado", "submit": True}
    p.update(kw)
    return p


def _create(**kw):
    r = requests.post(f"{API}/company/services", json=_payload(**kw), cookies=EMP)
    if r.status_code == 200:
        created.append(r.json()["id"])
    return r


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for sid in created:
        requests.delete(f"{API}/company/services/{sid}", cookies=EMP)


def test_sessions_valid():
    for c in (EMP, ADM, VIP):
        assert requests.get(f"{API}/auth/me", cookies=c).status_code == 200


def test_public_categories():
    r = requests.get(f"{API}/service-categories")
    assert r.status_code == 200
    slugs = [c["slug"] for c in r.json()]
    assert "limpieza" in slugs and "otros" in slugs
    assert all("_id" not in c for c in r.json())


def test_create_pending_and_list():
    r = _create()
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "pending" and d["price_usdt"] == 25
    assert d["availability"][0] == {"day": 0, "start": "09:00", "end": "12:00"}
    mine = requests.get(f"{API}/company/services", cookies=EMP).json()
    assert any(s["id"] == d["id"] for s in mine)


def test_price_validation():
    assert _create(price_usdt=0).status_code == 400
    r = _create(pricing_type="quote", price_usdt=0)
    assert r.status_code == 200 and r.json()["pricing_type"] == "quote"


def test_draft_then_submit():
    r = _create(submit=False)
    assert r.json()["status"] == "draft"
    sid = r.json()["id"]
    s = requests.post(f"{API}/company/services/{sid}/submit", cookies=EMP)
    assert s.status_code == 200 and s.json()["status"] == "pending"


def test_approve_publishes_public():
    sid = _create().json()["id"]
    pend = requests.get(f"{API}/admin/services?status=pending", cookies=ADM).json()
    assert any(s["id"] == sid for s in pend)
    a = requests.post(f"{API}/admin/services/{sid}/approve", cookies=ADM)
    assert a.status_code == 200 and a.json()["status"] == "published"
    pub = requests.get(f"{API}/services", cookies=VIP).json()
    assert any(s["id"] == sid for s in pub)
    assert requests.get(f"{API}/services/{sid}").status_code == 200


def test_reject_then_edit_resubmits():
    sid = _create().json()["id"]
    r = requests.post(f"{API}/admin/services/{sid}/reject", json={"reason": "TEST motivo"}, cookies=ADM)
    assert r.json()["status"] == "rejected" and r.json()["rejection_reason"] == "TEST motivo"
    u = requests.put(f"{API}/company/services/{sid}", json={"title": "TEST_fixed"}, cookies=EMP)
    assert u.json()["status"] == "pending" and u.json()["rejection_reason"] == ""


def test_edit_published_stays_published_without_review():
    """Documents moderation bypass: editing a published service keeps it public."""
    sid = _create().json()["id"]
    requests.post(f"{API}/admin/services/{sid}/approve", cookies=ADM)
    u = requests.put(f"{API}/company/services/{sid}", json={"title": "TEST_changed_after_approval"}, cookies=EMP)
    assert u.status_code == 200
    print("status after editing published:", u.json()["status"])


def test_non_company_forbidden():
    assert requests.get(f"{API}/company/services", cookies=VIP).status_code in (401, 403)
    assert requests.get(f"{API}/admin/services", cookies=VIP).status_code in (401, 403)


def test_category_crud():
    name = f"TEST Cat {uuid.uuid4().hex[:4]}"
    c = requests.post(f"{API}/admin/service-categories", json={"name": name, "active": True}, cookies=ADM)
    assert c.status_code == 200
    cid = c.json()["id"]
    t = requests.put(f"{API}/admin/service-categories/{cid}", json={"name": name, "active": False}, cookies=ADM)
    assert t.json()["active"] is False
    pub = [x["id"] for x in requests.get(f"{API}/service-categories").json()]
    assert cid not in pub
    d = requests.delete(f"{API}/admin/service-categories/{cid}", cookies=ADM)
    assert d.json()["deactivated"] is False
