"""STAFF-08b — DEPENDENCIAS DEL PERMISO 'products'.

Al CONCEDER `products` se activan por defecto las acciones que el flujo de
productos requiere (editar precios, subir imágenes, eliminar), para que no quede
un product manager A MEDIAS (podría abrir la sección pero recibir 403 al poner
precio/imagen o borrar). El admin puede desmarcarlas luego; una edición que NO
es una nueva concesión de `products` no las reactiva.
"""
import os
import uuid
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
EMP = "user_test_employee01"
FLAGS = ("can_edit_product_prices", "can_upload_product_images", "can_delete_products")


_DB_CLIENT = None


def _db():
    global _DB_CLIENT
    if _DB_CLIENT is None:
        _DB_CLIENT = MongoClient(os.environ["MONGO_URL"])
    return _DB_CLIENT[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _emp():
    return _db().users.find_one({"user_id": EMP}, {"_id": 0}) or {}


def _reset_emp():
    _db().users.update_one(
        {"user_id": EMP},
        {"$unset": {"allowed_permissions": "", **{f: "" for f in FLAGS}},
         "$set": {"role": "employee", "account_status": "active"}},
    )


def _put(fields):
    return requests.put(f"{API}/admin/users/{EMP}", headers=_hdr(ADMIN_TOKEN),
                        json=with_totp_admin(fields))


def test_staff08b_granting_products_enables_action_flags():
    _reset_emp()
    try:
        r = _put({"allowed_permissions": ["products"]})
        assert r.status_code == 200, r.text
        u = _emp()
        for f in FLAGS:
            assert u.get(f) is True, f"{f} debía activarse al conceder products"
    finally:
        _reset_emp()


def test_staff08b_explicit_flag_false_respected():
    _reset_emp()
    try:
        r = _put({"allowed_permissions": ["products"], "can_delete_products": False})
        assert r.status_code == 200, r.text
        u = _emp()
        assert u.get("can_edit_product_prices") is True
        assert u.get("can_upload_product_images") is True
        assert u.get("can_delete_products") is False  # intención explícita respetada
    finally:
        _reset_emp()


def test_staff08b_not_reexpanded_when_already_granted():
    # products YA concedido con delete deshabilitado manualmente: una edición que
    # NO es nueva concesión de products NO debe reactivar el flag.
    _reset_emp()
    _db().users.update_one({"user_id": EMP}, {"$set": {
        "allowed_permissions": ["products"], "can_delete_products": False,
        "can_edit_product_prices": True, "can_upload_product_images": True}})
    try:
        r = _put({"allowed_permissions": ["products", "orders"]})
        assert r.status_code == 200, r.text
        assert _emp().get("can_delete_products") is False
    finally:
        _reset_emp()


def test_staff08b_non_product_grant_untouched():
    _reset_emp()
    try:
        r = _put({"allowed_permissions": ["orders"]})
        assert r.status_code == 200, r.text
        u = _emp()
        for f in FLAGS:
            assert not u.get(f), f"{f} no debía activarse sin products"
    finally:
        _reset_emp()


def test_staff08b_end_to_end_no_half_done_product_manager():
    # Tras conceder products, el empleado crea un producto CON PRECIO sin 403.
    _reset_emp()
    name = "s08b " + uuid.uuid4().hex[:8]
    try:
        assert _put({"allowed_permissions": ["products"]}).status_code == 200
        r = requests.post(f"{API}/admin/products", headers=_hdr(EMPLOYEE_TOKEN),
                          json={"name": name, "price_usd": 10, "cost_usd": 5})
        assert r.status_code == 200, r.text  # ya no hay 403 de precios
    finally:
        _db().products.delete_many({"name": name})
        _reset_emp()
