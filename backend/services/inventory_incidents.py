"""IPV Fase 3 — Seguimiento de incidencias del inventario (iter333).

Registra y da ciclo de vida (pendiente → en_revision → resuelta) a las
incidencias del control físico:
  - conteo_pendiente: producto activo sin contar en la jornada.
  - diferencia: conteo con descuadre aún no ajustado.
  - venta_bajo_costo: venta a un precio por debajo del costo.

Dedup por `dedupe_key` (type + referencia) para no duplicar. Auto-resolución
cuando desaparece la causa (se cuenta el producto, se autoriza el ajuste de la
diferencia, el conteo queda sin descuadre). Una incidencia ya resuelta NO se
reabre: queda como constancia histórica.
"""
import uuid
import logging
import re
from typing import Optional

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from db_client import db
from auth_utils import now_utc, iso
from services.inventory import _COMPANY_FILTER, today_havana, UNIT_ABBR

logger = logging.getLogger(__name__)

STATUSES = ("pendiente", "en_revision", "resuelta")
# iter346 (H13) — alcance completo de la Fase 3: además de conteo pendiente,
# diferencia y venta bajo costo, se siguen 'costo pendiente' (existencia sin
# costo, no valorable) y 'documento faltante' (base sin documentar).
TYPES = ("conteo_pendiente", "diferencia", "venta_bajo_costo",
         "costo_pendiente", "documento_faltante")
_INDEX_READY = False

# iter346 (H13) — evidencia mínima exigida por tipo al RESOLVER manualmente.
_MIN_RESOLUTION_NOTE = 10
_RESOLVE_EVIDENCE_HINT = {
    "diferencia": "Referencia del conteo autorizado o del ajuste que corrige el descuadre.",
    "venta_bajo_costo": "Referencia del documento o autorización que justifica la venta bajo costo.",
    "costo_pendiente": "Costo asignado o referencia del documento de compra que fija el costo.",
    "documento_faltante": "Referencia de la apertura auditada o del documento que respalda la existencia.",
    "conteo_pendiente": "Motivo o documento que justifica cerrar el conteo pendiente.",
}


async def _ensure_index() -> None:
    global _INDEX_READY
    if not _INDEX_READY:
        await db.inventory_incidents.create_index(
            "dedupe_key", unique=True, sparse=True)
        await db.inventory_incidents.create_index(
            [("status", 1), ("type", 1), ("created_at", -1)])
        await db.inventory_incidents.create_index(
            [("base_key", 1), ("episode", -1)])
        # iter343 (H07) — backfill una vez de las incidencias heredadas al modelo
        # de episodios: su `dedupe_key` plano pasa a ser también `base_key` con
        # episode 1. Así `_latest_episode` las encuentra y NO se duplica un
        # abierto ya existente al introducir los episodios sucesores.
        await db.inventory_incidents.update_many(
            {"base_key": {"$exists": False},
             "dedupe_key": {"$exists": True, "$ne": None}},
            [{"$set": {"base_key": "$dedupe_key", "episode": 1}}])
        _INDEX_READY = True


async def _latest_episode(base_key: str) -> Optional[dict]:
    """Última incidencia (episodio más reciente) que comparte la causa."""
    return await db.inventory_incidents.find_one(
        {"base_key": base_key}, {"_id": 0},
        sort=[("episode", -1), ("created_at", -1)])


async def _upsert_incident(*, itype: str, product_id: str, product_name: str,
                           detail: str, amount: float, ref_id: str,
                           ref_date: str, base_key: str) -> str:
    """Registra la incidencia de una causa (identificada por `base_key`).

    iter343 (H07) — modelo de EPISODIOS para dar continuidad cuando una causa
    vuelve a aparecer:
      - Sin episodios previos → crea el episodio 1 (pendiente).
      - Episodio abierto en curso → refresca detalle/monto y deja constancia de
        la nueva observación (sin duplicar la incidencia ni el impacto).
      - Último episodio YA RESUELTO y la causa reaparece → crea un episodio
        SUCESOR abierto, enlazado al anterior (predecessor_id), conservando la
        evidencia de la resolución previa como constancia histórica.
    """
    await _ensure_index()
    now = iso(now_utc())
    amt = round(float(amount or 0), 2)
    latest = await _latest_episode(base_key)
    if latest and latest["status"] != "resuelta":
        changed = (latest.get("detail") != detail
                   or round(float(latest.get("amount") or 0), 2) != amt)
        upd: dict = {"$set": {"detail": detail, "amount": amt, "ref_id": ref_id,
                              "ref_date": ref_date, "updated_at": now}}
        if changed:
            # continuidad de observaciones dentro del episodio abierto
            upd["$push"] = {"history": {
                "status": latest["status"], "note": f"Nueva observación: {detail}",
                "by": "", "by_email": "sistema", "at": now}}
        await db.inventory_incidents.update_one({"id": latest["id"]}, upd)
        return latest["id"]
    episode = (int(latest.get("episode") or 1) + 1) if latest else 1
    predecessor_id = latest["id"] if latest else None
    if latest:
        note0 = (f"Reaparece la causa: episodio #{episode} sucesor de "
                 f"{predecessor_id} (resuelto {latest.get('resolved_at', '')[:10]}).")
    else:
        note0 = "Generada automáticamente"
    doc = {
        "id": str(uuid.uuid4()), "type": itype, "product_id": product_id,
        "product_name": product_name, "status": "pendiente", "detail": detail,
        "amount": amt, "ref_id": ref_id, "ref_date": ref_date,
        "base_key": base_key, "dedupe_key": f"{base_key}#ep{episode}",
        "episode": episode, "predecessor_id": predecessor_id, "source": "auto",
        "created_at": now, "updated_at": now, "auto_resolved": False,
        "history": [{"status": "pendiente", "note": note0, "by": "",
                     "by_email": "sistema", "at": now}],
    }
    try:
        await db.inventory_incidents.insert_one({**doc})
    except DuplicateKeyError:
        found = await db.inventory_incidents.find_one(
            {"dedupe_key": doc["dedupe_key"]}, {"_id": 0})
        return found["id"] if found else doc["id"]
    return doc["id"]


async def _auto_resolve(base_key: str, note: str) -> None:
    """Resuelve el episodio ABIERTO más reciente de la causa (si lo hay)."""
    now = iso(now_utc())
    inc = await _latest_episode(base_key)
    if not inc or inc["status"] == "resuelta":
        return
    await db.inventory_incidents.update_one(
        {"id": inc["id"]},
        {"$set": {"status": "resuelta", "updated_at": now, "resolved_at": now,
                  "resolved_by": "", "resolved_by_email": "sistema",
                  "resolution_note": note, "auto_resolved": True},
         "$push": {"history": {"status": "resuelta", "note": note, "by": "",
                               "by_email": "sistema", "at": now}}})


# ───────────────────── detectores (hooks automáticos) ─────────────────────
async def on_sale_below_cost(movement: dict) -> None:
    """Hook en record_movement: una venta cuyo total < costo de venta genera
    una incidencia de venta bajo costo (pérdida = costo − total)."""
    if movement.get("type") != "venta":
        return
    total = float(movement.get("total") or 0)
    cost_of_sale = float(movement.get("cost_of_sale") or 0)
    if cost_of_sale <= 0 or total >= cost_of_sale:
        return
    loss = round(cost_of_sale - total, 2)
    await _upsert_incident(
        itype="venta_bajo_costo", product_id=movement["product_id"],
        product_name=movement.get("product_name", ""),
        detail=(f"Venta a {total} CUP por debajo del costo {cost_of_sale} CUP "
                f"({movement.get('quantity')} ud) · pérdida {loss} CUP."),
        amount=loss, ref_id=movement.get("id", ""),
        ref_date=(movement.get("created_at") or "")[:10],
        base_key=f"venta_bajo_costo:{movement.get('id', '')}")


async def on_count_recorded(count: dict) -> None:
    """Hook en record_physical_count: resuelve el 'conteo pendiente' del
    producto y crea/resuelve la 'diferencia' según el descuadre."""
    pid = count["product_id"]
    day = count["count_date"]
    await _auto_resolve(f"conteo_pendiente:{pid}:{day}",
                        "El producto fue contado en la jornada.")
    # iter337 (H02) — conservar la precisión fraccionaria. El int() anterior
    # truncaba −0,75 lb a 0 y la incidencia de diferencia se auto-resolvía como
    # si el conteo cuadrara. Se usa el mismo criterio de cero que _count_status.
    diff = round(float(count.get("difference") or 0), 3)
    unit = UNIT_ABBR.get(count.get("unit") or "", count.get("unit") or "ud")
    dk = f"diferencia:{count.get('id', '')}"
    if abs(diff) > 1e-9 and not count.get("authorized"):
        await _upsert_incident(
            itype="diferencia", product_id=pid,
            product_name=count.get("product_name", ""),
            detail=(f"Descuadre de {diff:+g} {unit} (contado "
                    f"{count.get('counted_qty')} vs teórico "
                    f"{count.get('theoretical_stock')})."),
            amount=count.get("difference_value") or 0,
            ref_id=count.get("id", ""), ref_date=day, base_key=dk)
    else:
        await _auto_resolve(dk, "El conteo quedó sin diferencia.")


async def on_count_authorized(count_id: str) -> None:
    """Hook en authorize_count_adjustment: la diferencia queda ajustada."""
    await _auto_resolve(f"diferencia:{count_id}",
                        "Diferencia ajustada y autorizada.")


async def _sync_costo_pendiente(products: list, day: str) -> tuple:
    """iter346 (H13) — producto activo con existencia pero SIN costo asignado
    (cost_usd = 0): no puede valorarse. Se auto-resuelve al asignarle costo o
    al quedar sin existencia."""
    created = resolved = 0
    for p in products:
        stock = round(float(p.get("stock") or 0), 3)
        cost = float(p.get("cost_usd") or 0)
        unit = UNIT_ABBR.get(p.get("unit") or "", p.get("unit") or "ud")
        dk = f"costo_pendiente:{p['id']}"
        inc = await _latest_episode(dk)
        if stock > 1e-9 and cost <= 0:
            await _upsert_incident(
                itype="costo_pendiente", product_id=p["id"],
                product_name=p.get("name", ""),
                detail=(f"Existencia de {stock:g} {unit} sin costo asignado; "
                        f"no puede valorarse en el inventario."),
                amount=0, ref_id="", ref_date=day, base_key=dk)
            if not inc or inc["status"] == "resuelta":
                created += 1
        elif inc and inc["status"] != "resuelta":
            await _auto_resolve(
                dk, "Se asignó costo al producto o quedó sin existencia.")
            resolved += 1
    return created, resolved


async def _sync_documento_faltante(products: list, day: str) -> tuple:
    """iter346 (H13) — producto de la empresa con existencia SIN DOCUMENTAR (el
    'gap' de apertura auditada ya detectado por el sistema). Se auto-resuelve al
    registrar la apertura auditada que documenta la base."""
    from services.inventory_ipv import _undocumented_gap
    created = resolved = 0
    for p in products:
        if p.get("owner_id"):
            continue
        unit = UNIT_ABBR.get(p.get("unit") or "", p.get("unit") or "ud")
        dk = f"documento_faltante:{p['id']}"
        inc = await _latest_episode(dk)
        gap = await _undocumented_gap(p)
        if gap > 0.001:
            await _upsert_incident(
                itype="documento_faltante", product_id=p["id"],
                product_name=p.get("name", ""),
                detail=(f"Existencia sin documentar: {gap:g} {unit} sin "
                        f"movimiento de origen. Registra la apertura auditada."),
                amount=0, ref_id="", ref_date=day, base_key=dk)
            if not inc or inc["status"] == "resuelta":
                created += 1
        elif inc and inc["status"] != "resuelta":
            await _auto_resolve(
                dk, "La base quedó documentada (apertura auditada registrada).")
            resolved += 1
    return created, resolved


async def sync_pending_count_incidents(day: Optional[str] = None) -> dict:
    """Sincroniza las incidencias auto-detectadas por producto de una jornada:
    conteo pendiente, costo pendiente (iter346/H13) y documento faltante
    (iter346/H13). Crea una por cada producto activo de la empresa que aplique y
    resuelve las de los que dejaron de cumplir la causa. Pensada para correr a
    diario (y bajo demanda)."""
    d = (day or today_havana())[:10]
    products = await db.products.find(
        {**_COMPANY_FILTER, "is_active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "stock": 1, "cost_usd": 1,
         "owner_id": 1, "unit": 1}).to_list(5000)
    counted = {c["product_id"] for c in await db.inventory_counts.find(
        {"count_date": d}, {"_id": 0, "product_id": 1}).to_list(50000)}
    created = 0
    resolved = 0
    for p in products:
        dk = f"conteo_pendiente:{p['id']}:{d}"
        if p["id"] in counted:
            inc = await _latest_episode(dk)
            if inc and inc["status"] != "resuelta":
                await _auto_resolve(dk, "El producto fue contado en la jornada.")
                resolved += 1
        else:
            before = await _latest_episode(dk)
            await _upsert_incident(
                itype="conteo_pendiente", product_id=p["id"],
                product_name=p.get("name", ""),
                detail=f"Producto activo sin conteo en la jornada {d}.",
                amount=0, ref_id="", ref_date=d, base_key=dk)
            if not before or before["status"] == "resuelta":
                created += 1
    c2, r2 = await _sync_costo_pendiente(products, d)
    c3, r3 = await _sync_documento_faltante(products, d)
    return {"date": d, "created": created + c2 + c3,
            "resolved": resolved + r2 + r3}


# ───────────────────────── ciclo de vida / consulta ──────────────────────
async def transition_incident(incident_id: str, status: str, note: str,
                              actor: dict, evidence: str = "") -> dict:
    if status not in STATUSES:
        raise HTTPException(status_code=400, detail="Estado inválido")
    inc = await db.inventory_incidents.find_one({"id": incident_id}, {"_id": 0})
    if not inc:
        raise HTTPException(status_code=404, detail="Incidencia no encontrada")
    note = (note or "").strip()
    evidence = (evidence or "").strip()
    now = iso(now_utc())
    upd = {"status": status, "updated_at": now}
    hist_note = note
    if status == "resuelta":
        # iter346 (H13) — la resolución manual EXIGE una explicación y una
        # evidencia acorde al tipo; ya no se admite cerrar con nota vacía.
        if len(note) < _MIN_RESOLUTION_NOTE:
            raise HTTPException(
                status_code=400,
                detail=(f"La resolución exige una explicación de al menos "
                        f"{_MIN_RESOLUTION_NOTE} caracteres."))
        if not evidence:
            hint = _RESOLVE_EVIDENCE_HINT.get(inc.get("type"), "")
            raise HTTPException(
                status_code=400,
                detail=("Indica la evidencia que justifica la resolución. "
                        + hint).strip())
        upd.update({"resolved_at": now, "resolved_by": actor.get("user_id", ""),
                    "resolved_by_email": actor.get("email", ""),
                    "resolution_note": note, "resolution_evidence": evidence,
                    "auto_resolved": False})
        hist_note = f"{note} · Evidencia: {evidence}"
    await db.inventory_incidents.update_one(
        {"id": incident_id},
        {"$set": upd,
         "$push": {"history": {"status": status, "note": hist_note,
                               "by": actor.get("user_id", ""),
                               "by_email": actor.get("email", ""), "at": now}}})
    return await db.inventory_incidents.find_one({"id": incident_id}, {"_id": 0})


async def assign_incident(incident_id: str, assignee_id: str,
                          actor: dict) -> dict:
    """iter346 (H13) — asigna un RESPONSABLE (admin/staff) a la incidencia. El
    responsable es DISTINTO del autor de los cambios y queda registrado en el
    historial para auditoría."""
    inc = await db.inventory_incidents.find_one({"id": incident_id}, {"_id": 0})
    if not inc:
        raise HTTPException(status_code=404, detail="Incidencia no encontrada")
    user = await db.users.find_one(
        {"user_id": assignee_id},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1})
    if not user or user.get("role") not in ("admin", "employee"):
        raise HTTPException(
            status_code=400,
            detail="El responsable debe ser un usuario admin o staff.")
    now = iso(now_utc())
    name = user.get("name") or user.get("email") or assignee_id
    await db.inventory_incidents.update_one(
        {"id": incident_id},
        {"$set": {"assignee_id": assignee_id, "assignee_name": name,
                  "assignee_email": user.get("email", ""),
                  "assigned_by": actor.get("user_id", ""),
                  "assigned_by_email": actor.get("email", ""),
                  "assigned_at": now, "updated_at": now},
         "$push": {"history": {
             "status": inc["status"],
             "note": f"Responsable asignado: {name}",
             "by": actor.get("user_id", ""),
             "by_email": actor.get("email", ""), "at": now}}})
    return await db.inventory_incidents.find_one({"id": incident_id}, {"_id": 0})


async def list_assignees() -> list:
    """iter346 (H13) — usuarios admin/staff que pueden ser responsables."""
    users = await db.users.find(
        {"role": {"$in": ["admin", "employee"]}},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1}
    ).sort("name", 1).to_list(200)
    return [{"id": u["user_id"],
             "name": u.get("name") or u.get("email") or u["user_id"],
             "email": u.get("email", ""), "role": u.get("role", "")}
            for u in users]


async def list_incidents(status: Optional[str] = None,
                         itype: Optional[str] = None,
                         date_from: Optional[str] = None,
                         date_to: Optional[str] = None,
                         product_q: Optional[str] = None,
                         limit: int = 500) -> list:
    q: dict = {}
    if status:
        q["status"] = status
    if itype:
        q["type"] = itype
    # iter346 (H13) — filtros por fecha (sobre ref_date de la incidencia)...
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            rng["$gte"] = date_from[:10]
        if date_to:
            rng["$lte"] = date_to[:10]
        q["ref_date"] = rng
    # ...y por producto (coincidencia parcial sobre el nombre).
    if product_q and product_q.strip():
        q["product_name"] = {"$regex": re.escape(product_q.strip()),
                             "$options": "i"}
    return await db.inventory_incidents.find(
        q, {"_id": 0}).sort([("status", 1), ("created_at", -1)]).to_list(limit)


async def incident_summary() -> dict:
    agg = await db.inventory_incidents.aggregate([
        {"$group": {"_id": {"s": "$status", "t": "$type"},
                    "n": {"$sum": 1}}}]).to_list(100)
    by_status: dict = {}
    by_type: dict = {}
    open_total = 0
    for a in agg:
        s = a["_id"]["s"]
        t = a["_id"]["t"]
        n = a["n"]
        by_status[s] = by_status.get(s, 0) + n
        by_type[t] = by_type.get(t, 0) + n
        if s != "resuelta":
            open_total += n
    return {"by_status": by_status, "by_type": by_type, "open": open_total}
