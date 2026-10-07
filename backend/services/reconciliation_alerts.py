"""iter347 — Aviso Conciliación.

Avisa a los admins (push + email + campana) cuando un extracto bancario TERMINA
de procesarse, con el resumen de movimientos IDENTIFICADOS (conciliados
automáticamente + marcados para revisión) frente a los no identificados. Reúsa
exactamente el mismo mecanismo de avisos que el resto de alertas de admin
(`admin_alerts.notify_all_admins` + `routes.notifications._insert_notification`).
"""
import logging

from db_client import db

logger = logging.getLogger(__name__)

_STATUS_ES = {
    "processed": "procesado",
    "partially_processed": "procesado parcialmente",
}


async def notify_reconciliation_done(imp: dict, *, status: str, detected: int,
                                     auto: int, review: int, unmatched: int,
                                     duplicates: int, notes: str = "") -> None:
    """Notifica a los admins el fin del procesamiento de un extracto con el
    resumen de identificados. Pensada para estados terminales con resultado
    (processed / partially_processed)."""
    import_id = imp.get("id")
    bank = imp.get("bank_name") or "—"
    currency = imp.get("currency") or ""
    fname = imp.get("original_file_name") or "extracto"
    identified = int(auto) + int(review)
    status_es = _STATUS_ES.get(status, status)

    title = f"Conciliación lista: {bank}"
    body = (
        f"El extracto «{fname}» ({currency}) quedó {status_es}. "
        f"{detected} movimiento(s) detectado(s): {identified} identificado(s) "
        f"({auto} conciliado(s) automáticamente, {review} por revisar), "
        f"{unmatched} sin identificar"
        + (f", {duplicates} duplicado(s)" if duplicates else "")
        + "."
    )
    if notes:
        body += f" Nota: {notes}"

    url_path = "/admin/reconciliation"
    try:
        from admin_alerts import notify_all_admins
        await notify_all_admins(db, title=title, body=body, url_path=url_path)
    except Exception as e:  # noqa: BLE001
        logger.error(f"reconciliation alert push/email failed: {e}")
    try:
        from routes.notifications import _insert_notification
        admins = await db.users.find(
            {"role": "admin"}, {"_id": 0, "user_id": 1}).to_list(50)
        for a in admins:
            await _insert_notification(
                recipient_user_id=a["user_id"], type="reconciliation_done",
                title=title, message=body,
                data={"import_id": import_id, "status": status,
                      "detected": detected, "identified": identified,
                      "auto": auto, "review": review, "unmatched": unmatched,
                      "duplicates": duplicates})
    except Exception as e:  # noqa: BLE001
        logger.error(f"reconciliation alert in-app notify failed: {e}")
