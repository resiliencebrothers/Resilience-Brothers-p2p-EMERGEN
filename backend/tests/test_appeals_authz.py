"""Extra authorization regression: non-staff (normal + vip) cannot reach the
staff appeal queue. Complements test_appeals.py which covered admin/employee.
"""
import requests

from tests.conftest import BASE_URL, VIP_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def test_vip_forbidden_admin_appeals():
    r = requests.get(f"{API}/admin/appeals", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 403, r.text


def test_normal_forbidden_admin_appeals():
    r = requests.get(f"{API}/admin/appeals", headers=_hdr(NORMAL_TOKEN))
    assert r.status_code == 403, r.text


def test_normal_forbidden_resolve():
    # No real appeal id required — auth check happens before the DB lookup.
    r = requests.post(
        f"{API}/admin/appeals/fake-id/resolve",
        headers=_hdr(NORMAL_TOKEN),
        json={"response": "should never see this"},
    )
    assert r.status_code == 403, r.text
