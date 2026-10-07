"""iter347 — Aviso Conciliación: al terminar de procesar un extracto, los
admins reciben una notificación (campana) con el resumen de identificados.

Prueba el servicio de aviso de forma aislada (el push/email son best-effort y
están envueltos en try/except; la campana es la parte determinista)."""
import uuid

import pytest

from db_client import db
from services.reconciliation_alerts import notify_reconciliation_done

pytestmark = pytest.mark.asyncio


async def _cleanup(uid):
    await db.users.delete_many({"user_id": uid})
    await db.notifications.delete_many({"recipient_user_id": uid})


async def test_reconciliation_done_notifies_admins_with_summary():
    uid = f"u_admin_recon_{uuid.uuid4().hex[:6]}"
    await db.users.insert_one({
        "user_id": uid, "name": "Admin Recon", "role": "admin",
        "email": "admin.recon@resilience.com"})
    try:
        imp = {"id": "imp_test_347", "bank_name": "BPA", "currency": "CUP",
               "original_file_name": "extracto_mayo.csv"}
        await notify_reconciliation_done(
            imp, status="processed", detected=12, auto=7, review=2,
            unmatched=3, duplicates=1, notes="")
        notif = await db.notifications.find_one(
            {"recipient_user_id": uid, "type": "reconciliation_done"},
            {"_id": 0}, sort=[("created_at", -1)])
        assert notif is not None
        assert notif["data"]["identified"] == 9  # 7 auto + 2 review
        assert notif["data"]["auto"] == 7
        assert notif["data"]["unmatched"] == 3
        assert notif["data"]["import_id"] == "imp_test_347"
        # El cuerpo resume los identificados y los sin identificar.
        assert "9 identificado" in notif["message"]
        assert "7 conciliado" in notif["message"]
        assert "3 sin identificar" in notif["message"]
        assert "1 duplicado" in notif["message"]
        assert "BPA" in notif["title"]
    finally:
        await _cleanup(uid)


async def test_reconciliation_done_partial_status_label():
    uid = f"u_admin_recon_{uuid.uuid4().hex[:6]}"
    await db.users.insert_one({
        "user_id": uid, "name": "Admin Recon 2", "role": "admin",
        "email": "admin.recon2@resilience.com"})
    try:
        imp = {"id": "imp_test_347b", "bank_name": "Banco Metropolitano",
               "currency": "USD", "original_file_name": "mayo.xlsx"}
        await notify_reconciliation_done(
            imp, status="partially_processed", detected=5, auto=0, review=0,
            unmatched=5, duplicates=0, notes="Algunas filas con errores.")
        notif = await db.notifications.find_one(
            {"recipient_user_id": uid, "type": "reconciliation_done"},
            {"_id": 0}, sort=[("created_at", -1)])
        assert notif is not None
        assert "procesado parcialmente" in notif["message"]
        assert "0 identificado" in notif["message"]
        assert "Nota: Algunas filas con errores." in notif["message"]
        assert notif["data"]["status"] == "partially_processed"
    finally:
        await _cleanup(uid)
