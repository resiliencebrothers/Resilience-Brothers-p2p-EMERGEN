"""iter21: granular employee permissions for marketplace (prices / images / delete)."""
import os
import uuid
import requests
from pymongo import MongoClient

from conftest import BASE_URL, make_admin_totp


def _db():
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli, cli[os.environ["DB_NAME"]]


EMP_USER_ID = "user_test_emp_iter21"
EMP_SESSION = "test_session_emp_iter21"


def _seed_employee(**perms):
    """Create a fresh employee user + valid session every test."""
    cli, db = _db()
    db.users.delete_many({"user_id": EMP_USER_ID})
    db.user_sessions.delete_many({"user_id": EMP_USER_ID})
    db.users.insert_one({
        "user_id": EMP_USER_ID,
        "email": "emp.iter21@example.com",
        "name": "Test Employee",
        "role": "employee",
        "auth_provider": "google",
        "email_verified": True,
        "can_edit_product_prices": perms.get("price", False),
        "can_upload_product_images": perms.get("image", False),
        "can_delete_products": perms.get("delete", False),
        "created_at": "2026-06-01T00:00:00Z",
    })
    db.user_sessions.insert_one({
        "user_id": EMP_USER_ID,
        "session_token": EMP_SESSION,
        "expires_at": "2030-01-01T00:00:00Z",
        "created_at": "2026-06-01T00:00:00Z",
    })
    cli.close()


def _seed_product():
    cli, db = _db()
    pid = f"prod_iter21_{uuid.uuid4().hex[:8]}"
    db.products.insert_one({
        "id": pid,
        "name": "Test Product",
        "description": "desc",
        "image_url": "https://example.com/old.jpg",
        "price_usd": 10.0,
        "cost_usd": 4.0,
        "stock": 100,
        "category": "general",
        "is_active": True,
    })
    cli.close()
    return pid


def _put_product(token: str, pid: str, **fields):
    base = {
        "name": "Test Product",
        "description": "desc",
        "image_url": "https://example.com/old.jpg",
        "price_usd": 10.0,
        "cost_usd": 4.0,
        "stock": 100,
        "category": "general",
        "is_active": True,
    }
    base.update(fields)
    return requests.put(
        f"{BASE_URL}/api/admin/products/{pid}",
        headers={"Authorization": f"Bearer {token}"},
        json=base,
    )


def _cleanup():
    cli, db = _db()
    db.products.delete_many({"id": {"$regex": "^prod_iter21_"}})
    db.users.delete_many({"user_id": EMP_USER_ID})
    db.user_sessions.delete_many({"user_id": EMP_USER_ID})
    cli.close()


class TestEmployeeProductPerms:
    def teardown_method(self, _): _cleanup()

    # ---------- Price edits ----------
    def test_employee_without_price_perm_cannot_change_price(self):
        _seed_employee()
        pid = _seed_product()
        r = _put_product(EMP_SESSION, pid, price_usd=99.0)
        assert r.status_code == 403
        assert "precio" in r.json()["detail"].lower()

    def test_employee_without_price_perm_cannot_change_cost(self):
        _seed_employee()
        pid = _seed_product()
        r = _put_product(EMP_SESSION, pid, cost_usd=7.0)
        assert r.status_code == 403

    def test_employee_with_price_perm_can_change_price(self):
        _seed_employee(price=True)
        pid = _seed_product()
        r = _put_product(EMP_SESSION, pid, price_usd=99.0)
        assert r.status_code == 200, r.text
        assert r.json()["price_usd"] == 99.0

    def test_employee_without_perms_can_still_edit_unrelated_fields(self):
        """Stock and description aren't restricted, so an employee with no
        marketplace perms can still tweak them as long as price/image stay."""
        _seed_employee()
        pid = _seed_product()
        r = _put_product(EMP_SESSION, pid, stock=42, description="updated")
        assert r.status_code == 200
        assert r.json()["stock"] == 42

    # ---------- Image edits ----------
    def test_employee_without_image_perm_cannot_change_image(self):
        _seed_employee()
        pid = _seed_product()
        r = _put_product(EMP_SESSION, pid, image_url="https://example.com/new.jpg")
        assert r.status_code == 403
        assert "imágen" in r.json()["detail"].lower()

    def test_employee_with_image_perm_can_change_image(self):
        _seed_employee(image=True)
        pid = _seed_product()
        r = _put_product(EMP_SESSION, pid, image_url="https://example.com/new.jpg")
        assert r.status_code == 200
        assert r.json()["image_url"] == "https://example.com/new.jpg"

    def test_partial_perms_only_unlock_their_field(self):
        """Image perm only — cannot change price."""
        _seed_employee(image=True)
        pid = _seed_product()
        r = _put_product(EMP_SESSION, pid, image_url="https://e.com/x.jpg", price_usd=200.0)
        assert r.status_code == 403

    # ---------- Delete ----------
    def test_employee_without_delete_perm_cannot_delete(self):
        _seed_employee()
        pid = _seed_product()
        r = requests.delete(
            f"{BASE_URL}/api/admin/products/{pid}",
            headers={"Authorization": f"Bearer {EMP_SESSION}"},
        )
        assert r.status_code == 403

    def test_employee_with_delete_perm_can_delete(self):
        _seed_employee(delete=True)
        pid = _seed_product()
        r = requests.delete(
            f"{BASE_URL}/api/admin/products/{pid}",
            headers={"Authorization": f"Bearer {EMP_SESSION}"},
        )
        assert r.status_code == 200

    # ---------- Create ----------
    def test_employee_without_perms_cannot_create_with_price(self):
        _seed_employee()
        r = requests.post(
            f"{BASE_URL}/api/admin/products",
            headers={"Authorization": f"Bearer {EMP_SESSION}"},
            json={"name": "X", "description": "", "image_url": "",
                  "price_usd": 50.0, "cost_usd": 0, "stock": 10,
                  "category": "general", "is_active": True},
        )
        assert r.status_code == 403

    # ---------- Admin bypass ----------
    def test_admin_bypasses_all_perms(self):
        pid = _seed_product()
        r = _put_product("test_session_admin_X", pid,
                         price_usd=999.0, image_url="https://e.com/admin.jpg")
        assert r.status_code == 200
        assert r.json()["price_usd"] == 999.0

    # ---------- Admin can grant perms via /admin/users ----------
    def test_admin_can_toggle_employee_perm(self):
        _seed_employee()
        r = requests.put(
            f"{BASE_URL}/api/admin/users/{EMP_USER_ID}",
            headers={"Authorization": "Bearer test_session_admin_X"},
            json={"can_edit_product_prices": True, "totp_code": make_admin_totp()},
        )
        assert r.status_code == 200, r.text
        assert r.json()["can_edit_product_prices"] is True

    def test_new_employees_default_to_no_perms(self):
        """Sanity check on the User model default."""
        _seed_employee()
        cli, db = _db()
        u = db.users.find_one({"user_id": EMP_USER_ID}, {"_id": 0})
        cli.close()
        assert u["can_edit_product_prices"] is False
        assert u["can_upload_product_images"] is False
        assert u["can_delete_products"] is False
