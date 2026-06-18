"""Quick curl-style verification of admin step-up 2FA endpoints against deployed URL."""
import os
import sys
from pathlib import Path
import requests
import pyotp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv
load_dotenv(ROOT / "frontend" / ".env")
load_dotenv(ROOT / "backend" / ".env")

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN = {"Authorization": "Bearer test_session_admin_X"}
EMPLOYEE = {"Authorization": "Bearer test_session_employee_X"}
SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def now_code():
    return pyotp.TOTP(SECRET).now()


def show(label, r):
    body = r.text[:300]
    print(f"[{label}] {r.status_code} -> {body}")


# 1) Admin settings: 401 without TOTP, 200 with valid TOTP, 403 for employee
print("--- /api/admin/settings ---")
r = requests.put(f"{BASE}/api/admin/settings", headers=ADMIN, json={"defensive_mode": False})
show("admin no-totp", r)
assert r.status_code == 401 and "TOTP_CODE_REQUIRED" in r.text, r.text

r = requests.put(f"{BASE}/api/admin/settings", headers=ADMIN, json={"defensive_mode": False, "totp_code": now_code()})
show("admin valid-totp", r)
assert r.status_code == 200

r = requests.put(f"{BASE}/api/admin/settings", headers=EMPLOYEE, json={"defensive_mode": False, "totp_code": now_code()})
show("employee forbidden", r)
assert r.status_code == 403

# 2) Admin rates list to find an existing rate id
print("--- /api/admin/rates ---")
r = requests.get(f"{BASE}/api/rates", headers=ADMIN)
print("rates list:", r.status_code, len(r.json()) if r.status_code == 200 else r.text[:200])
rates = r.json() if r.status_code == 200 else []
if rates:
    rid = rates[0].get("id")
    body = {k: v for k, v in rates[0].items() if k in ("from_code", "to_code", "rate_normal", "rate_vip", "real_rate", "active")}
    # PUT without totp -> 401
    r = requests.put(f"{BASE}/api/admin/rates/{rid}", headers=ADMIN, json=body)
    show("rate no-totp", r)
    assert r.status_code == 401 and "TOTP_CODE_REQUIRED" in r.text
    body["totp_code"] = now_code()
    r = requests.put(f"{BASE}/api/admin/rates/{rid}", headers=ADMIN, json=body)
    show("rate valid-totp", r)
    assert r.status_code == 200

# 3) Admin users update — only test 401 path on a known-safe user to avoid mutation
print("--- /api/admin/users update ---")
r = requests.put(f"{BASE}/api/admin/users/user_test_normal01", headers=ADMIN, json={"role": "normal"})
show("user no-totp", r)
assert r.status_code == 401 and "TOTP_CODE_REQUIRED" in r.text

r = requests.put(f"{BASE}/api/admin/users/user_test_normal01", headers=ADMIN, json={"role": "normal", "totp_code": now_code()})
show("user valid-totp", r)
assert r.status_code == 200

print("\nALL CURL CHECKS PASSED")
