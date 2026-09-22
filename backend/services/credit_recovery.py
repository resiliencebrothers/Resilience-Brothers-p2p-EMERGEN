"""iter249 — Acreditaciones EXACTAMENTE-UNA-VEZ con recuperación ante fallos.

Problema reportado: algunas acreditaciones marcaban el documento como
"procesado" ANTES de sumar el dinero; si la base de datos fallaba entre ambos
pasos, el saldo quedaba sin acreditar y el reintento se bloqueaba (el flag ya
estaba consumido). MongoDB corre standalone (sin transacciones multi-doc), así
que se usa el patrón outbox de documento único:

  1. El doc origen reclama la operación (flag) Y registra la intención
     (`credit_pending` = {op_id, user_id, code, amount}) en el MISMO update
     atómico.
  2. El abono usa `credit_balance_idempotent` (el $inc y el registro del op_id
     ocurren en UNA operación sobre el doc del usuario → un reintento nunca
     duplica).
  3. Se limpia el marker.

Si el proceso muere entre pasos, `heal_pending_credits()` (scheduler cada 2
min + arranque) completa la acreditación pendiente: nunca se pierde dinero,
nunca se duplica, y el reintento no queda bloqueado.
"""
import logging
from datetime import datetime, timezone, timedelta

from db_client import db
# Re-export: los call sites históricos importan estas primitivas desde aquí.
from services.credit_markers import pending_marker, apply_and_clear  # noqa: F401

logger = logging.getLogger(__name__)

# Colecciones cuyo flujo escribe markers `credit_pending`.
PENDING_COLLECTIONS = ("orders", "deposits", "redemptions", "withdrawals",
                       "deliveries", "capital_requests", "users",
                       "vip_capital_deposits", "vip_batch_items")


async def heal_pending_credits(max_age_seconds: int = 90) -> int:
    """Completa acreditaciones que quedaron a medias (crash entre el claim y
    el abono). Solo toca markers con antigüedad > max_age_seconds para no
    pisar peticiones en vuelo. Idempotente: el op_id evita duplicados."""
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=max_age_seconds)).isoformat()
    healed = 0
    for name in PENDING_COLLECTIONS:
        key = "user_id" if name == "users" else "id"
        rows = await db[name].find(
            {"credit_pending.at": {"$lt": cutoff}},
            {"_id": 0, key: 1, "credit_pending": 1},
        ).to_list(200)
        for row in rows:
            cp = row.get("credit_pending") or {}
            if not cp.get("op_id") or not cp.get("user_id"):
                await db[name].update_one({key: row[key]},
                                          {"$unset": {"credit_pending": ""}})
                continue
            # iter254(R04) — marker sin preparar: el importe bruto NO se
            # acredita; para order-accum se recalcula la amortización
            # (idempotente por orden) y se fija el neto antes de abonar.
            if cp.get("prepared") is False:
                if name == "orders" and str(cp.get("op_id", "")).startswith("order-accum"):
                    order = await db.orders.find_one(
                        {"id": row[key]},
                        {"_id": 0, "id": 1, "user_id": 1, "to_code": 1})
                    if not order:
                        await db[name].update_one({key: row[key]},
                                                  {"$unset": {"credit_pending": ""}})
                        continue
                    from services.balances import _apply_capital_request_repayment
                    net = await _apply_capital_request_repayment(
                        cp["user_id"], cp["code"], float(cp["amount"]),
                        order["id"])
                    if net <= 0:
                        await db[name].update_one({key: row[key]},
                                                  {"$unset": {"credit_pending": ""}})
                        healed += 1
                        continue
                    cp["amount"] = round(float(net), 8)
                    cp["prepared"] = True
                    await db[name].update_one(
                        {key: row[key], "credit_pending.op_id": cp["op_id"]},
                        {"$set": {"credit_pending.amount": cp["amount"],
                                  "credit_pending.prepared": True}})
                else:
                    logger.warning("credit_pending sin preparar de origen "
                                   "desconocido: %s/%s op=%s — no se acredita",
                                   name, row[key], cp.get("op_id"))
                    continue
            applied = await apply_and_clear(name, row[key], cp, key_field=key)
            healed += 1
            logger.warning(
                "credit_pending sanado: %s/%s op=%s +%s %s → %s (aplicado=%s)",
                name, row[key], cp["op_id"], cp["amount"], cp["code"],
                cp["user_id"], applied)
    return healed


async def _reverse_fund_inflow_for_cycle(rid: str) -> None:
    """R05 — reverso idempotente de la entrada al fondo del ciclo rechazado.
    Mismo dedupe_key que el reverso del rechazo (fund-reverse:{rid}:c{n}):
    corra quien corra primero, el fondo recibe UNA sola compensación."""
    fresh = await db.redemptions.find_one({"id": rid}, {"_id": 0}) or {}
    amt = float(fresh.get("fund_inflow_amount") or 0)
    if not fresh.get("fund_inflow_at") or fresh.get("fund_inflow_reversed_at") \
            or amt <= 0:
        return
    cycle = int(fresh.get("rejection_cycle") or 1)
    from services.company_funds_common import record_auto_fund_adjustment
    await record_auto_fund_adjustment(
        adjustment_type="outflow",
        currency=fresh.get("fund_inflow_currency") or "USDT", amount=amt,
        source_name="Marketplace tienda",
        note=(f"Reverso por canje rechazado: {fresh.get('quantity')}× "
              f"{fresh.get('product_name', '')} (canje {rid[:8]})"),
        ref_id=rid, dedupe_key=f"fund-reverse:{rid}:c{cycle}")
    await db.redemptions.update_one(
        {"id": rid, "fund_inflow_reversed_at": {"$in": [None, ""]}},
        {"$set": {"fund_inflow_reversed_at":
                  datetime.now(timezone.utc).isoformat()}})


async def _settle_rejected_fund_trace(rid: str) -> bool:
    """R05 — el canje se rechazó con la entrada al fondo aún pendiente. Si el
    asiento c0 ALCANZÓ a publicarse (ejecutor lento o crash tras publicar),
    se compensa con el reverso idempotente del ciclo; si no existe, no hay
    nada que revertir AQUÍ — un ingreso publicado más tarde por el escritor
    original lo detecta y compensa el barrido durable por asiento (V03,
    `heal_initializing_ops`), que no depende de este plan borrable."""
    inflow = await db.company_fund_adjustments.find_one(
        {"dedupe_key": f"fund-inflow:{rid}:c0"}, {"_id": 0})
    if inflow:
        await db.redemptions.update_one(
            {"id": rid, "fund_inflow_at": {"$in": [None, ""]}},
            {"$set": {"fund_inflow_at": inflow.get("created_at"),
                      "fund_inflow_amount": inflow.get("amount"),
                      "fund_inflow_currency": inflow.get("currency")}})
        try:
            await _reverse_fund_inflow_for_cycle(rid)
        except Exception as e:
            logger.error("reverso de entrada tardía %s: %s", rid, e)
            return False
        await db.company_fund_adjustments.update_one(
            {"dedupe_key": f"fund-inflow:{rid}:c0"},
            {"$set": {"marks_ensured": True}})
    await db.redemptions.update_one(
        {"id": rid, "sale_trace_pending.fund": True},
        {"$set": {"sale_trace_pending.fund": False}})
    return True


async def ensure_company_sale_traces(r: dict) -> bool:
    """MR02 — asegura los DOS rastros de una venta web de producto de EMPRESA
    marcados pendientes en la activación del canje (`sale_trace_pending`):
    el movimiento de inventario 'venta' (dedupe único por canje/ciclo, R04) y
    la entrada al fondo (dedupe_key único). Recuperable e idempotente:
    repetirlo jamás vuelve a cobrar al cliente ni descuenta mercancía. Un
    canje ya rechazado NO registra la entrada al fondo; si la entrada llegó a
    publicarse en la carrera, se compensa (R05)."""
    rid = str(r.get("id") or "")
    pend = r.get("sale_trace_pending") or {}
    if not rid or not pend:
        return True
    now = datetime.now(timezone.utc).isoformat()
    ok = True
    if pend.get("inv"):
        exists = await db.inventory_movements.find_one(
            {"ref_id": rid, "type": "venta", "source": "marketplace"},
            {"_id": 1})
        if not exists:
            product = await db.products.find_one(
                {"id": r.get("product_id")}, {"_id": 0})
            if product and not product.get("owner_id"):
                try:
                    from services.inventory import record_movement
                    # R04 — identidad única del movimiento de venta por canje
                    # y ciclo: creador y recuperador solapados escriben UNO.
                    await record_movement(
                        product=product, mtype="venta",
                        quantity=int(r.get("quantity") or 0),
                        note=f"Canje marketplace de {r.get('user_name', '')}",
                        source="marketplace", ref_id=rid,
                        actor={"user_id": r.get("user_id") or "",
                               "name": r.get("user_name") or ""},
                        apply_stock=False,
                        dedupe_key=f"sale-trace:{rid}:c0")
                    exists = True
                except Exception as e:
                    ok = False
                    logger.error("venta de inventario pendiente %s: %s", rid, e)
            else:
                exists = True  # producto borrado o de vendedor: nada que trazar
        if exists:
            await db.redemptions.update_one(
                {"id": rid, "sale_trace_pending.inv": True},
                {"$set": {"sale_trace_pending.inv": False}})
    if pend.get("fund"):
        # R05 — decisión durable ANTES de publicar: el claim exige que el
        # canje NO esté rechazado en este preciso momento (no en la copia
        # leída al entrar).
        claim = await db.redemptions.update_one(
            {"id": rid, "sale_trace_pending.fund": True,
             "status": {"$ne": "rejected"}},
            {"$set": {"sale_trace_pending.fund_claim_at": now}})
        if claim.matched_count == 0:
            # rechazado (o tarea ya resuelta): el ciclo se compensó — o se
            # compensa aquí — sin dejar capital huérfano.
            still = await db.redemptions.find_one(
                {"id": rid, "sale_trace_pending.fund": True}, {"_id": 1})
            if still:
                ok = await _settle_rejected_fund_trace(rid) and ok
        else:
            total = round(float(r.get("total_usd") or 0), 2)
            store_note = ""
            if r.get("store_currency"):
                store_note = (f" (≈ {float(r.get('total_store') or 0):g} "
                              f"{r['store_currency']})")
            try:
                from services.company_funds_common import record_auto_fund_adjustment
                await record_auto_fund_adjustment(
                    adjustment_type="inflow", currency="USDT", amount=total,
                    source_name="Marketplace tienda",
                    note=(f"Venta web: {r.get('quantity')}× "
                          f"{r.get('product_name', '')} = {total:.2f} USDT"
                          f"{store_note} (canje {rid[:8]})"),
                    ref_id=rid, dedupe_key=f"fund-inflow:{rid}:c0")
                await db.redemptions.update_one(
                    {"id": rid, "fund_inflow_at": {"$in": [None, ""]}},
                    {"$set": {"fund_inflow_at": now,
                              "fund_inflow_amount": total,
                              "fund_inflow_currency": "USDT"}})
                # V03 — marcas aseguradas: el barrido durable por asiento ya
                # no necesita re-visitar este ingreso.
                await db.company_fund_adjustments.update_one(
                    {"dedupe_key": f"fund-inflow:{rid}:c0"},
                    {"$set": {"marks_ensured": True}})
                # R05 — post-verificación: un rechazo que corrió en paralelo
                # (entre el claim y el asiento) deja el ciclo compensado aquí
                # mismo con el reverso idempotente.
                fresh = await db.redemptions.find_one(
                    {"id": rid}, {"_id": 0, "status": 1}) or {}
                if fresh.get("status") == "rejected":
                    await _reverse_fund_inflow_for_cycle(rid)
                await db.redemptions.update_one(
                    {"id": rid, "sale_trace_pending.fund": True},
                    {"$set": {"sale_trace_pending.fund": False}})
            except Exception as e:
                ok = False
                logger.error("entrada al fondo pendiente %s: %s", rid, e)
    if ok:
        await db.redemptions.update_one(
            {"id": rid, "sale_trace_pending.inv": {"$ne": True},
             "sale_trace_pending.fund": {"$ne": True}},
            {"$unset": {"sale_trace_pending": ""}})
    return ok


async def heal_initializing_ops(max_age_seconds: int = 120) -> int:
    """iter254(R03) / iter256(S03,S04,S10) — resuelve de forma DETERMINISTA los
    intentos que murieron a medias en el protocolo reserva/operación/activación.

    Orden crítico (S03): primero se RECLAMA la propiedad del intento
    (initializing → failed_init, update condicional); solo si el claim gana se
    compensa. Un creador lento que pierde el claim detecta matched_count=0 al
    activar y deshace sus propios efectos (mismos op_ids ⇒ exactamente-una-vez).
    Los failed_init que conservan op_ids (crash a mitad de la compensación) se
    re-compensan de forma idempotente."""
    from services.balances import credit_balance_idempotent as _credit
    from services.balances import op_was_applied, debit_balance_idempotent
    from services.inventory import (apply_stock_idempotent, movement_delta,
                                    stock_op_was_applied)
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=max_age_seconds)).isoformat()
    healed = 0

    # --- retiros a medio crear -------------------------------------------
    rows = await db.withdrawals.find(
        {"$or": [{"status": "initializing", "created_at": {"$lt": cutoff}},
                 {"status": "failed_init", "init_op_id": {"$exists": True}}]},
        {"_id": 0, "id": 1, "user_id": 1, "currency": 1, "init_op_id": 1,
         "amount_usd": 1, "courier_fee_currency_amount": 1,
         "status": 1}).to_list(100)
    for w in rows:
        if w.get("status") == "initializing":
            claim = await db.withdrawals.update_one(
                {"id": w["id"], "status": "initializing"},
                {"$set": {"status": "failed_init"}})
            if claim.modified_count == 0:
                continue  # el creador lo activó primero: NO compensar (S03)
        op = w.get("init_op_id") or ""
        amount = (float(w.get("amount_usd") or 0)
                  + float(w.get("courier_fee_currency_amount") or 0))
        if op and await op_was_applied(w["user_id"], op):
            await _credit(w["user_id"], w.get("currency") or "USD", amount,
                          f"{op}:undo")
        await db.withdrawals.update_one(
            {"id": w["id"], "status": "failed_init"},
            {"$unset": {"init_op_id": ""}})
        healed += 1
        logger.warning("retiro initializing revertido: %s", w["id"])

    # --- canjes a medio crear --------------------------------------------
    rows = await db.redemptions.find(
        {"$or": [{"status": "initializing", "created_at": {"$lt": cutoff}},
                 {"status": "failed_init", "init_op_id": {"$exists": True}},
                 {"status": "failed_init", "stock_op_id": {"$exists": True}}]},
        {"_id": 0, "id": 1, "user_id": 1, "settlement_currency": 1,
         "init_op_id": 1, "stock_op_id": 1, "product_id": 1, "quantity": 1,
         "total_usd": 1, "courier_fee_usd": 1, "status": 1}).to_list(100)
    for r in rows:
        if r.get("status") == "initializing":
            claim = await db.redemptions.update_one(
                {"id": r["id"], "status": "initializing"},
                {"$set": {"status": "failed_init"}})
            if claim.modified_count == 0:
                continue  # el creador lo activó primero: NO compensar (S03)
        stock_op = r.get("stock_op_id") or ""
        if stock_op and await stock_op_was_applied(r["product_id"], stock_op):
            await apply_stock_idempotent(r["product_id"],
                                         int(r.get("quantity") or 0),
                                         f"{stock_op}:undo",
                                         require_available=False)
        op = r.get("init_op_id") or ""
        amount = (float(r.get("total_usd") or 0)
                  + float(r.get("courier_fee_usd") or 0))
        if op and await op_was_applied(r["user_id"], op):
            await _credit(r["user_id"],
                          r.get("settlement_currency") or "USDT", amount,
                          f"{op}:undo")
        await db.redemptions.update_one(
            {"id": r["id"], "status": "failed_init"},
            {"$unset": {"init_op_id": "", "stock_op_id": ""}})
        healed += 1
        logger.warning("canje initializing revertido: %s", r["id"])

    # --- reactivaciones de canje a medias (S04/D04) -------------------------
    rows = await db.redemptions.find(
        {"status": "rejected", "reactivation_pending.at": {"$lt": cutoff}},
        {"_id": 0, "id": 1, "user_id": 1, "product_id": 1, "quantity": 1,
         "reactivation_pending": 1}).to_list(100)
    for r in rows:
        plan = r.get("reactivation_pending") or {}
        stock_op = plan.get("stock_op") or ""
        debit_op = plan.get("debit_op") or ""
        cur = plan.get("currency") or "USDT"
        # iter257(D04) — reclamar la PROPIEDAD del aborto antes de compensar:
        # si el plan ya no está (el endpoint publicó el estado nuevo), no se
        # toca nada. Planes ya 'aborting' viejos = abortador muerto → resumir.
        if plan.get("state") != "aborting":
            claim = await db.redemptions.update_one(
                {"id": r["id"], "status": "rejected",
                 "reactivation_pending.stock_op": stock_op,
                 "reactivation_pending.state": {"$exists": False}},
                {"$set": {"reactivation_pending.state": "aborting"}})
            if claim.modified_count == 0:
                continue
        # iter260(E08) — quemar-o-compensar ATÓMICO: si el creador lento aún
        # no aplicó el débito/reserva, la quema los vuelve 'duplicate' (jamás
        # se aplicarán); si ya se aplicaron, se compensan. Borrar el plan ya
        # no puede dejar un débito tardío sin reverso.
        from services.balances import burn_or_undo_debit
        from services.inventory import burn_or_undo_stock
        if debit_op:
            await burn_or_undo_debit(r["user_id"], cur,
                                     float(plan.get("amount") or 0), debit_op)
        if stock_op:
            await burn_or_undo_stock(r["product_id"],
                                     int(plan.get("quantity")
                                         or r.get("quantity") or 0), stock_op)
        await db.redemptions.update_one(
            {"id": r["id"], "reactivation_pending.stock_op": stock_op},
            {"$unset": {"reactivation_pending": ""}})
        healed += 1
        logger.warning("reactivación de canje revertida: %s", r["id"])

    # --- ítems de lote legado con efecto de ledger pendiente (E02) ----------
    rows = await db.vip_batch_items.find(
        {"ledger_pending.at": {"$lt": cutoff}},
        {"_id": 0, "id": 1, "vip_user_id": 1, "ledger_pending": 1}).to_list(100)
    for it in rows:
        lp = it.get("ledger_pending") or {}
        op = lp.get("op_id") or ""
        if op:
            from services.vip_batch_ops import apply_ledger_delta_idempotent
            await apply_ledger_delta_idempotent(
                it["vip_user_id"], lp.get("direction") or "credit",
                float(lp.get("delta_usdt") or 0), op)
        await db.vip_batch_items.update_one(
            {"id": it["id"], "ledger_pending.op_id": op},
            {"$unset": {"ledger_pending": ""}})
        healed += 1
        logger.warning("ledger de ítem de lote completado por el healer: %s",
                       it["id"])

    # --- settlements con efecto pendiente (D03) -----------------------------
    rows = await db.vip_settlements.find(
        {"status": "confirmed", "settle_pending.at": {"$lt": cutoff}},
        {"_id": 0, "id": 1, "vip_user_id": 1, "settle_pending": 1}).to_list(100)
    for s in rows:
        plan = s.get("settle_pending") or {}
        op = plan.get("op_id") or ""
        amt = float(plan.get("amount_usdt") or 0)
        if plan.get("direction") == "payout":
            st = await debit_balance_idempotent(s["vip_user_id"], "USDT",
                                                amt, op)
            if st == "insufficient":
                await db.vip_settlements.update_one(
                    {"id": s["id"], "settle_pending.op_id": op},
                    {"$set": {"status": "pending"},
                     "$unset": {"settle_pending": ""}})
                logger.warning("settlement %s sin saldo: vuelve a pendiente",
                               s["id"])
                healed += 1
                continue
        else:
            if not await db.vip_ledger.find_one(
                    {"vip_user_id": s["vip_user_id"]}, {"_id": 1}):
                await db.vip_ledger.insert_one({
                    "vip_user_id": s["vip_user_id"], "positive_usdt": 0.0,
                    "negative_usdt": 0.0,
                    "updated_at": datetime.now(timezone.utc).isoformat()})
            await db.vip_ledger.update_one(
                {"vip_user_id": s["vip_user_id"], "applied_ops": {"$ne": op}},
                {"$inc": {"negative_usdt": -amt}, "$push": {"applied_ops": op}})
        await db.vip_settlements.update_one(
            {"id": s["id"], "settle_pending.op_id": op},
            {"$unset": {"settle_pending": ""}})
        healed += 1
        logger.warning("settlement %s completado por el healer", s["id"])

    # --- movimientos de inventario sin stock aplicado ---------------------
    rows = await db.inventory_movements.find(
        {"needs_stock": True, "stock_applied": {"$ne": True},
         "stock_apply_failed": {"$ne": True},
         "created_at": {"$lt": cutoff}}, {"_id": 0}).to_list(200)
    for m in rows:
        delta = movement_delta(m.get("type") or "", int(m.get("quantity") or 0))
        st = await apply_stock_idempotent(m["product_id"], delta,
                                          f"invmov:{m['id']}",
                                          require_available=(delta < 0))
        if st == "insufficient":
            # iter256(S10) — fallido ≠ aplicado: no cuenta en KPIs ni cierre.
            await db.inventory_movements.update_one(
                {"id": m["id"]}, {"$set": {"stock_apply_failed": True}})
            logger.warning("movimiento %s: stock insuficiente al recuperar", m["id"])
        else:
            await db.inventory_movements.update_one(
                {"id": m["id"]}, {"$set": {"stock_applied": True}})
            # iter256(S10) — completar también el asiento contable del fondo
            # (idempotente por flag fund_flow_recorded).
            try:
                from services.inventory import _record_fund_flow
                await _record_fund_flow(m)
            except Exception as e:
                logger.error("fund flow al recuperar movimiento %s: %s",
                             m["id"], e)
        healed += 1

    # --- asientos contables de inventario perdidos (D08) --------------------
    rows = await db.inventory_movements.find(
        {"stock_applied": True, "fund_flow_recorded": {"$ne": True},
         "created_at": {"$lt": cutoff}, "total": {"$gt": 0},
         "$or": [{"type": "venta", "source": "manual"},
                 {"type": "entrada", "source": {"$in": ["manual", "alta"]}}]},
        {"_id": 0}).to_list(100)
    for m in rows:
        try:
            from services.inventory import _record_fund_flow
            await _record_fund_flow(m)
            healed += 1
        except Exception as e:
            logger.error("fund flow catchup %s: %s", m["id"], e)

    # --- re-débitos de reactivación de retiros a medias -------------------
    rows = await db.withdrawals.find(
        {"redebit_pending.at": {"$lt": cutoff}},
        {"_id": 0, "id": 1, "user_id": 1, "redebit_pending": 1}).to_list(100)
    for w in rows:
        rp = w.get("redebit_pending") or {}
        op = rp.get("op_id") or ""
        if not op:
            await db.withdrawals.update_one({"id": w["id"]},
                                            {"$unset": {"redebit_pending": ""}})
            continue
        st = await debit_balance_idempotent(w["user_id"],
                                            rp.get("currency") or "USD",
                                            float(rp.get("amount") or 0), op)
        if st == "insufficient":
            # el cliente gastó el reembolso: el retiro vuelve a 'rejected'.
            await db.withdrawals.update_one(
                {"id": w["id"]},
                {"$set": {"status": "rejected", "balance_refunded": True},
                 "$unset": {"redebit_pending": ""}})
        else:
            await db.withdrawals.update_one(
                {"id": w["id"], "redebit_pending.op_id": op},
                {"$unset": {"redebit_pending": ""}})
        healed += 1

    # --- planes de tarifa de mensajería interrumpidos (ME01) ----------------
    from services.courier_fee import heal_courier_fee_plans
    healed += await heal_courier_fee_plans(cutoff)

    # --- planes de carga de lotes interrumpidos (R03) -----------------------
    from services.vip_batch_ops import heal_batch_upload_plans
    healed += await heal_batch_upload_plans(cutoff)

    # --- liquidaciones vinculadas pendientes tras confirmar entrega (ME03) --
    rows = await db.deliveries.find(
        {"status": "confirmed", "settlement_pending.at": {"$lt": cutoff}},
        {"_id": 0, "id": 1, "settlement_pending": 1}).to_list(100)
    for dv in rows:
        sp = dv.get("settlement_pending") or {}
        try:
            from services.delivery_settlement import settle_linked_operation
            await settle_linked_operation(
                sp.get("kind") or "", sp.get("ref_id") or "",
                {"user_id": "system", "name": "Sistema", "email": "",
                 "role": "admin"})
            await db.deliveries.update_one(
                {"id": dv["id"], "settlement_pending.at": sp.get("at")},
                {"$unset": {"settlement_pending": ""}})
            healed += 1
            logger.warning("liquidación vinculada completada por el healer: "
                           "entrega %s → %s %s", dv["id"], sp.get("kind"),
                           sp.get("ref_id"))
        except Exception as e:
            logger.error("liquidación vinculada de %s sigue pendiente: %s",
                         dv["id"], e)

    # --- rastros de venta de productos de empresa pendientes (MR02) ---------
    rows = await db.redemptions.find(
        {"sale_trace_pending.at": {"$lt": cutoff}}, {"_id": 0}).to_list(100)
    for r in rows:
        if await ensure_company_sale_traces(r):
            healed += 1

    # --- V03: ingresos de venta publicados sin marcas en el canje -----------
    # La tarea durable es el PROPIO asiento (clave fund-inflow:{rid}:c{n}):
    # aunque otro ejecutor haya borrado el plan `sale_trace_pending`, un
    # ingreso tardío del escritor original se detecta aquí, se reponen las
    # marcas del canje y — si el canje está rechazado — se compensa con el
    # reverso idempotente del ciclo. Cada asiento se procesa UNA vez
    # (flag `marks_ensured`).
    rows = await db.company_fund_adjustments.find(
        {"adjustment_type": "inflow", "source": "marketplace_auto",
         "dedupe_key": {"$regex": "^fund-inflow:"},
         "marks_ensured": {"$ne": True},
         "created_at": {"$lt": cutoff}},
        {"_id": 0, "id": 1, "ref_id": 1, "amount": 1, "currency": 1,
         "created_at": 1}).to_list(200)
    for adj in rows:
        rid = str(adj.get("ref_id") or "")
        red = await db.redemptions.find_one({"id": rid},
                                            {"_id": 0, "status": 1}) if rid else None
        if not red:
            await db.company_fund_adjustments.update_one(
                {"id": adj["id"]}, {"$set": {"marks_ensured": True}})
            continue
        await db.redemptions.update_one(
            {"id": rid, "fund_inflow_at": {"$in": [None, ""]}},
            {"$set": {"fund_inflow_at": adj.get("created_at"),
                      "fund_inflow_amount": adj.get("amount"),
                      "fund_inflow_currency": adj.get("currency")}})
        if red.get("status") == "rejected":
            try:
                await _reverse_fund_inflow_for_cycle(rid)
            except Exception as e:
                logger.error("reverso de ingreso huérfano %s: %s", rid, e)
                continue  # sin flag: se reintenta en el próximo ciclo
        await db.company_fund_adjustments.update_one(
            {"id": adj["id"]}, {"$set": {"marks_ensured": True}})
        healed += 1
        logger.warning("ingreso de venta sin marcas reconciliado: canje %s",
                       rid)
    return healed
