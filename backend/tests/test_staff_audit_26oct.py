"""Auditoría Staff (26-10-2026) — STAFF-04, STAFF-05, STAFF-07.

- STAFF-04: ejecutar como mensajero (/courier/*) exige is_courier; ser staff
  (admin/employee) ya NO basta.
- STAFF-05: una cuenta de staff suspendida/en revisión pierde el acceso de
  inmediato (403) aunque su sesión siga viva.
- STAFF-07: un empleado con 'user_functions' NO puede modificar funciones de
  una cuenta de staff NI sus propias funciones/alcance (auto-escalada).
"""
import os
import uuid
import concurrent.futures
import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, NORMAL_TOKEN,
    with_totp_employee, with_totp_admin,
)

API = f"{BASE_URL}/api"
EMP = "user_test_employee01"
ADMIN = "user_test_admin01"
NORMAL = "user_test_normal01"


_DB_CLIENT = None


def _db():
    # Cliente cacheado a nivel de módulo: abrir uno nuevo por llamada agota los
    # puertos efímeros al correr junto a toda la batería (AutoReconnect).
    global _DB_CLIENT
    if _DB_CLIENT is None:
        _DB_CLIENT = MongoClient(os.environ["MONGO_URL"])
    return _DB_CLIENT[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _set(uid, fields):
    _db().users.update_one({"user_id": uid}, {"$set": fields})


def _unset(uid, fields):
    _db().users.update_one({"user_id": uid}, {"$unset": {f: "" for f in fields}})


# ------------------------------------------------------------------
# STAFF-04 — /courier/* exige is_courier
# ------------------------------------------------------------------

def test_staff04_courier_requires_is_courier_flag():
    # Empleado SIN is_courier → 403 aunque tenga el permiso 'deliveries'.
    _set(EMP, {"is_courier": False, "allowed_permissions": ["deliveries"]})
    try:
        r = requests.get(f"{API}/courier/deliveries", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 403, r.text
        assert "mensajero" in r.text.lower()
        # Con la marca is_courier → pasa el gate de rol de mensajero.
        _set(EMP, {"is_courier": True})
        r = requests.get(f"{API}/courier/deliveries", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 200, r.text
    finally:
        _set(EMP, {"is_courier": False})
        _unset(EMP, ["allowed_permissions"])


def test_staff04_admin_without_is_courier_blocked():
    # Un admin sin is_courier tampoco pasa /courier/* (solo mensajeros).
    _set(ADMIN, {"is_courier": False})
    r = requests.get(f"{API}/courier/deliveries", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 403, r.text


# ------------------------------------------------------------------
# STAFF-05 — staff suspendido pierde acceso de inmediato
# ------------------------------------------------------------------

def test_staff05_suspended_employee_denied():
    _set(EMP, {"allowed_permissions": ["deliveries"], "account_status": "blocked"})
    try:
        r = requests.get(f"{API}/admin/deliveries", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 403, r.text
        assert "suspend" in r.text.lower() or "revisión" in r.text.lower()
        # under_review también bloquea a staff.
        _set(EMP, {"account_status": "under_review"})
        r = requests.get(f"{API}/admin/deliveries", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 403, r.text
        # Al volver a 'active' recupera el acceso (con su permiso).
        _set(EMP, {"account_status": "active"})
        r = requests.get(f"{API}/admin/deliveries", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 200, r.text
    finally:
        _unset(EMP, ["allowed_permissions"])
        _set(EMP, {"account_status": "active"})


# ------------------------------------------------------------------
# STAFF-07 — sin auto-escalada ni edición de otras cuentas de staff
# ------------------------------------------------------------------

def test_staff07_employee_cannot_edit_own_functions():
    _set(EMP, {"allowed_permissions": ["users", "user_functions"]})
    try:
        r = requests.put(f"{API}/admin/users/{EMP}", headers=_hdr(EMPLOYEE_TOKEN),
                         json=with_totp_employee({"allowed_currencies": ["USD", "EUR"]}))
        assert r.status_code == 403, r.text
        # El empleado ES staff: queda bloqueado por el guard de cuenta-staff
        # (que subsume la auto-edición). Lo importante: NO puede escalar.
        body = r.text.lower()
        assert "propias" in body or "staff" in body
    finally:
        _unset(EMP, ["allowed_permissions"])


def test_staff07_employee_cannot_edit_staff_target():
    _set(EMP, {"allowed_permissions": ["users", "user_functions"]})
    try:
        # Objetivo = un admin → no puede tocar sus funciones.
        r = requests.put(f"{API}/admin/users/{ADMIN}", headers=_hdr(EMPLOYEE_TOKEN),
                         json=with_totp_employee({"allowed_currencies": ["USD"]}))
        assert r.status_code == 403, r.text
        assert "staff" in r.text.lower()
    finally:
        _unset(EMP, ["allowed_permissions"])


def test_staff07_employee_can_edit_normal_user_scope():
    # Control: editar el alcance de un CLIENTE normal sí está permitido.
    _set(EMP, {"allowed_permissions": ["users", "user_functions"]})
    prev = (_db().users.find_one({"user_id": NORMAL}, {"allowed_currencies": 1, "_id": 0})
            or {}).get("allowed_currencies")
    try:
        r = requests.put(f"{API}/admin/users/{NORMAL}", headers=_hdr(EMPLOYEE_TOKEN),
                         json=with_totp_employee({"allowed_currencies": ["USD"]}))
        assert r.status_code == 200, r.text
    finally:
        _unset(EMP, ["allowed_permissions"])
        if prev is None:
            _unset(NORMAL, ["allowed_currencies"])
        else:
            _set(NORMAL, {"allowed_currencies": prev})


# ------------------------------------------------------------------
# STAFF-06 — el feed en vivo (SSE) exige cuenta de staff activa
# ------------------------------------------------------------------

def test_staff06_suspended_staff_cannot_open_live_stream():
    _set(EMP, {"account_status": "blocked"})
    try:
        r = requests.get(f"{API}/live/stream", headers=_hdr(EMPLOYEE_TOKEN),
                         stream=True, timeout=10)
        try:
            assert r.status_code == 403, r.text
            assert "suspend" in r.text.lower() or "revisión" in r.text.lower()
        finally:
            r.close()
    finally:
        _set(EMP, {"account_status": "active"})


def test_staff06_normal_user_live_stream_ok():
    # Un cliente normal (no staff) abre el feed sin problema.
    r = requests.get(f"{API}/live/stream", headers=_hdr(NORMAL_TOKEN),
                     stream=True, timeout=10)
    try:
        assert r.status_code == 200, r.text
    finally:
        r.close()



# ------------------------------------------------------------------
# STAFF-07-R — is_courier sujeta a las restricciones de objetivo/autoedición
# ------------------------------------------------------------------
# Un empleado con 'users' + 'deliveries' (sin 'user_functions') NO puede
# reponer/alterar la marca is_courier sobre SÍ MISMO ni sobre otra cuenta de
# staff/admin; sí puede designar mensajeros CLIENTES. El admin puede sobre todos.

def _is_courier(uid):
    return bool((_db().users.find_one({"user_id": uid}, {"is_courier": 1, "_id": 0})
                 or {}).get("is_courier"))


def test_staff07r_employee_cannot_self_enable_courier():
    # El admin le retira is_courier pero conserva users+deliveries.
    _set(EMP, {"is_courier": False, "allowed_permissions": ["users", "deliveries"]})
    try:
        r = requests.put(f"{API}/admin/users/{EMP}", headers=_hdr(EMPLOYEE_TOKEN),
                         json=with_totp_employee({"is_courier": True}))
        assert r.status_code == 403, r.text
        assert "mensajero" in r.text.lower()
        assert _is_courier(EMP) is False, "la marca NO debe haberse escrito"
    finally:
        _set(EMP, {"is_courier": False})
        _unset(EMP, ["allowed_permissions"])


def test_staff07r_employee_cannot_set_courier_on_admin():
    _set(EMP, {"allowed_permissions": ["users", "deliveries"]})
    _set(ADMIN, {"is_courier": False})
    try:
        r = requests.put(f"{API}/admin/users/{ADMIN}", headers=_hdr(EMPLOYEE_TOKEN),
                         json=with_totp_employee({"is_courier": True}))
        assert r.status_code == 403, r.text
        assert "staff" in r.text.lower()
        assert _is_courier(ADMIN) is False, "la marca NO debe haberse escrito sobre el admin"
    finally:
        _unset(EMP, ["allowed_permissions"])


def test_staff07r_employee_cannot_set_courier_on_other_staff():
    # Objetivo = otro empleado (cuenta de staff) → prohibido.
    _set(EMP, {"allowed_permissions": ["users", "deliveries"]})
    _db().users.update_one(
        {"user_id": "user_test_employee02"},
        {"$setOnInsert": {"email": "emp2.staff07r@test.local", "role": "employee",
                          "account_status": "active"}},
        upsert=True,
    )
    _set("user_test_employee02", {"role": "employee", "is_courier": False})
    try:
        r = requests.put(f"{API}/admin/users/user_test_employee02",
                         headers=_hdr(EMPLOYEE_TOKEN),
                         json=with_totp_employee({"is_courier": True}))
        assert r.status_code == 403, r.text
        assert "staff" in r.text.lower()
        assert _is_courier("user_test_employee02") is False
    finally:
        _unset(EMP, ["allowed_permissions"])
        _db().users.delete_one({"user_id": "user_test_employee02"})


def test_staff07r_employee_can_designate_normal_client_courier():
    # Caso positivo: designar a un CLIENTE normal como mensajero sí se permite.
    _set(EMP, {"allowed_permissions": ["users", "deliveries"]})
    _set(NORMAL, {"is_courier": False})
    try:
        r = requests.put(f"{API}/admin/users/{NORMAL}", headers=_hdr(EMPLOYEE_TOKEN),
                         json=with_totp_employee({"is_courier": True}))
        assert r.status_code == 200, r.text
        assert _is_courier(NORMAL) is True
    finally:
        _unset(EMP, ["allowed_permissions"])
        _set(NORMAL, {"is_courier": False})


def test_staff07r_admin_can_assign_courier_anywhere():
    # Asignación legítima por administrador (sobre un cliente normal).
    _set(NORMAL, {"is_courier": False})
    try:
        r = requests.put(f"{API}/admin/users/{NORMAL}", headers=_hdr(ADMIN_TOKEN),
                         json=with_totp_admin({"is_courier": True}))
        assert r.status_code == 200, r.text
        assert _is_courier(NORMAL) is True
    finally:
        _set(NORMAL, {"is_courier": False})


# ------------------------------------------------------------------
# STAFF-05-R — la suspensión alcanza también el circuito de mensajero
# ------------------------------------------------------------------
# Un mensajero (is_courier=true) con account_status blocked/under_review NO
# puede operar NINGUNA ruta /courier/* (listar, aceptar, actualizar estado,
# caja...). Rehabilitar a 'active' recupera el acceso. Aplica igual a staff y a
# clientes-mensajeros; el onboarding normal de clientes (sin is_courier) no se
# ve afectado porque nunca llegan al guard.

_COURIER_CALLS = [
    ("get", "/courier/deliveries", None),               # listado
    ("get", "/courier/deliveries/history", None),       # historial
    ("post", "/courier/deliveries/fake-id/claim", {}),  # aceptación
    ("post", "/courier/deliveries/fake-id/status", {"status": "on_the_way"}),  # estado
    ("post", "/courier/location", {"lat": 23.1, "lng": -82.3}),  # ubicación
    ("post", "/courier/deliveries/fake-id/incident", {"note": "x"}),  # incidencia
    ("get", "/courier/cash", None),                     # caja del mensajero
]


def _call(method, path, token, body):
    fn = getattr(requests, method)
    kw = {"headers": _hdr(token)}
    if body is not None:
        kw["json"] = body
    return fn(f"{API}{path}", **kw)


def test_staff05r_blocked_courier_denied_all_routes():
    # Mensajero empleado activo → luego suspendido en sesión abierta.
    _set(EMP, {"is_courier": True, "allowed_permissions": ["deliveries"],
               "account_status": "blocked"})
    try:
        for method, path, body in _COURIER_CALLS:
            r = _call(method, path, EMPLOYEE_TOKEN, body)
            assert r.status_code == 403, f"{method} {path} -> {r.status_code} {r.text}"
            assert "suspend" in r.text.lower() or "revisión" in r.text.lower(), \
                f"{path}: {r.text}"
    finally:
        _set(EMP, {"is_courier": False, "account_status": "active"})
        _unset(EMP, ["allowed_permissions"])


def test_staff05r_under_review_courier_denied():
    _set(EMP, {"is_courier": True, "allowed_permissions": ["deliveries"],
               "account_status": "under_review"})
    try:
        r = _call("get", "/courier/deliveries", EMPLOYEE_TOKEN, None)
        assert r.status_code == 403, r.text
        assert "revisión" in r.text.lower() or "suspend" in r.text.lower()
    finally:
        _set(EMP, {"is_courier": False, "account_status": "active"})
        _unset(EMP, ["allowed_permissions"])


def test_staff05r_rehab_restores_courier_access():
    # Suspendido → 403; al volver a 'active' recupera el listado (is_courier
    # sigue concedido).
    _set(EMP, {"is_courier": True, "allowed_permissions": ["deliveries"],
               "account_status": "blocked"})
    try:
        r = _call("get", "/courier/deliveries", EMPLOYEE_TOKEN, None)
        assert r.status_code == 403, r.text
        _set(EMP, {"account_status": "active"})
        r = _call("get", "/courier/deliveries", EMPLOYEE_TOKEN, None)
        assert r.status_code == 200, r.text
    finally:
        _set(EMP, {"is_courier": False, "account_status": "active"})
        _unset(EMP, ["allowed_permissions"])


def test_staff05r_client_courier_blocked_also_denied():
    # Cliente-mensajero (NORMAL con is_courier) suspendido → también 403.
    _set(NORMAL, {"is_courier": True, "account_status": "blocked"})
    try:
        r = _call("get", "/courier/deliveries", NORMAL_TOKEN, None)
        assert r.status_code == 403, r.text
        assert "suspend" in r.text.lower() or "revisión" in r.text.lower()
    finally:
        _set(NORMAL, {"is_courier": False, "account_status": "active"})


def test_staff05r_normal_onboarding_unaffected():
    # Control: un cliente normal SIN is_courier nunca entra al circuito de
    # mensajero — recibe el 403 de "solo mensajeros", NO el de suspensión. Su
    # account_status (p. ej. under_review de onboarding) es irrelevante aquí.
    _set(NORMAL, {"is_courier": False, "account_status": "under_review"})
    try:
        r = _call("get", "/courier/deliveries", NORMAL_TOKEN, None)
        assert r.status_code == 403, r.text
        assert "mensajero" in r.text.lower()
        assert "suspend" not in r.text.lower() and "revisión" not in r.text.lower()
    finally:
        _set(NORMAL, {"account_status": "active"})



# ------------------------------------------------------------------
# STAFF-09 — dos decisiones sobre el mismo trabajo (apelaciones + soporte)
# ------------------------------------------------------------------
# Escritura condicional por estado esperado (compare-and-swap): dos revisores
# que leyeron el mismo estado NO pueden grabar ambas decisiones. Se prueba con
# BARRERAS DE CONCURRENCIA reales (hilos), no solo ejecuciones consecutivas.

def _mk_pending_appeal():
    aid = "s09a_" + uuid.uuid4().hex[:12]
    _db().appeals.insert_one({
        "id": aid, "user_id": NORMAL, "user_email": "n@t", "user_name": "N",
        "user_phone": "", "message": "please review my account now please",
        "status": "pending", "staff_response": None, "resolved_by": None,
        "resolved_by_email": None, "resolved_at": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    return aid


def test_staff09_appeal_loser_cannot_overwrite_decision():
    # Reviewer-1 ya ganó (estado ya NO es pending) → la 2ª decisión recibe 409
    # y NO sobrescribe la decisión vigente.
    _set(EMP, {"allowed_permissions": ["appeals"]})
    aid = _mk_pending_appeal()
    try:
        _db().appeals.update_one({"id": aid}, {"$set": {
            "status": "resolved", "resolved_by": "reviewer1",
            "resolved_by_email": "r1@t", "staff_response": "R1 original"}})
        r = requests.post(f"{API}/admin/appeals/{aid}/reject",
                          headers=_hdr(EMPLOYEE_TOKEN),
                          json={"response": "R2 intenta pisar"})
        assert r.status_code == 409, r.text
        doc = _db().appeals.find_one({"id": aid}, {"_id": 0})
        assert doc["status"] == "resolved"
        assert doc["resolved_by"] == "reviewer1"
        assert doc["staff_response"] == "R1 original"
    finally:
        _db().appeals.delete_one({"id": aid})
        _unset(EMP, ["allowed_permissions"])


def test_staff09_appeal_concurrent_two_reviewers_exactly_one_wins():
    _set(EMP, {"allowed_permissions": ["appeals"]})
    aid = _mk_pending_appeal()
    try:
        def decide(kind):
            return requests.post(f"{API}/admin/appeals/{aid}/{kind}",
                                 headers=_hdr(EMPLOYEE_TOKEN),
                                 json={"response": f"decision {kind}"}).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(decide, "resolve")
            f2 = ex.submit(decide, "reject")
            codes = sorted([f1.result(), f2.result()])
        assert codes == [200, 409], f"debe haber exactamente un ganador: {codes}"
        doc = _db().appeals.find_one({"id": aid}, {"_id": 0})
        assert doc["status"] in ("resolved", "rejected")
        assert doc["resolved_by"] == EMP
    finally:
        _db().appeals.delete_one({"id": aid})
        _unset(EMP, ["allowed_permissions"])


def _mk_ticket(status="open"):
    tid = "s09t_" + uuid.uuid4().hex[:12]
    _db().support_tickets.insert_one({
        "id": tid, "user_id": NORMAL, "subject": "concurrency", "category": "other",
        "status": status, "messages": [{"sender": "client", "text": "hi", "images": []}],
        "unread_by_staff": True, "unread_by_client": False,
        "closed_at": None, "closed_by": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    })
    return tid


def test_staff09_support_reply_cannot_land_on_closed():
    # Una respuesta del staff NO puede caer sobre un ticket ya cerrado (ni
    # reabrirlo ni añadir el mensaje).
    _set(EMP, {"allowed_permissions": ["support"]})
    tid = _mk_ticket("closed")
    _db().support_tickets.update_one({"id": tid}, {"$set": {
        "closed_by": "first_closer", "closed_at": "2026-01-01T00:00:00+00:00"}})
    try:
        r = requests.post(f"{API}/admin/support/tickets/{tid}/reply",
                          headers=_hdr(EMPLOYEE_TOKEN), json={"text": "late reply"})
        assert r.status_code in (400, 409), r.text
        doc = _db().support_tickets.find_one({"id": tid}, {"_id": 0})
        assert doc["status"] == "closed"
        assert len(doc["messages"]) == 1  # no se añadió la respuesta tardía
        assert doc["closed_by"] == "first_closer"
    finally:
        _db().support_tickets.delete_one({"id": tid})
        _unset(EMP, ["allowed_permissions"])


def test_staff09_client_reply_cannot_reopen_closed():
    tid = _mk_ticket("closed")
    try:
        r = requests.post(f"{API}/support/tickets/{tid}/reply",
                          headers=_hdr(NORMAL_TOKEN), json={"text": "reopen pls"})
        assert r.status_code in (400, 409), r.text
        doc = _db().support_tickets.find_one({"id": tid}, {"_id": 0})
        assert doc["status"] == "closed"
        assert len(doc["messages"]) == 1
    finally:
        _db().support_tickets.delete_one({"id": tid})


def test_staff09_support_close_vs_inflight_reply_barrier():
    # Barrera de concurrencia cierre-vs-respuesta: si el cierre tiene éxito, el
    # ticket queda cerrado (una respuesta en vuelo NO lo reabre).
    _set(EMP, {"allowed_permissions": ["support"]})
    tid = _mk_ticket("open")
    try:
        def reply():
            return requests.post(f"{API}/admin/support/tickets/{tid}/reply",
                                 headers=_hdr(EMPLOYEE_TOKEN),
                                 json={"text": "inflight reply"}).status_code

        def close():
            return requests.post(f"{API}/admin/support/tickets/{tid}/close",
                                 headers=_hdr(EMPLOYEE_TOKEN)).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            fr = ex.submit(reply)
            fc = ex.submit(close)
            rc, cc = fr.result(), fc.result()
        assert cc == 200, f"close debe ser 200 (idempotente): {cc}"
        # La respuesta gana (200) o PIERDE: 409 (cierre entre lectura y escritura,
        # CAS) o 400 (ya estaba cerrado al leer). Cualquier pérdida es válida.
        assert rc in (200, 400, 409), f"reply inesperado: {rc}"
        doc = _db().support_tickets.find_one({"id": tid}, {"_id": 0})
        assert doc["status"] == "closed", f"estado final debe ser closed: {doc['status']}"
    finally:
        _db().support_tickets.delete_one({"id": tid})
        _unset(EMP, ["allowed_permissions"])


def test_staff09_support_double_close_preserves_first_closer():
    # Dos cierres concurrentes: el segundo es no-op idempotente; closed_by del
    # PRIMERO no se sobrescribe.
    _set(EMP, {"allowed_permissions": ["support"]})
    tid = _mk_ticket("open")
    try:
        r1 = requests.post(f"{API}/admin/support/tickets/{tid}/close",
                           headers=_hdr(EMPLOYEE_TOKEN))
        assert r1.status_code == 200, r1.text
        first = _db().support_tickets.find_one({"id": tid}, {"_id": 0})
        first_closer, first_at = first["closed_by"], first["closed_at"]
        r2 = requests.post(f"{API}/admin/support/tickets/{tid}/close",
                           headers=_hdr(ADMIN_TOKEN))
        assert r2.status_code == 200, r2.text  # idempotente
        again = _db().support_tickets.find_one({"id": tid}, {"_id": 0})
        assert again["closed_by"] == first_closer
        assert again["closed_at"] == first_at
    finally:
        _db().support_tickets.delete_one({"id": tid})
        _unset(EMP, ["allowed_permissions"])
