"""Cálculo de turnos reservables (Fase 2 — Reserva de turnos).

A partir del HORARIO semanal del servicio (`availability`: ventanas por día de
la semana), su `duration_minutes`/`buffer_minutes` y su `capacity`, genera los
turnos concretos de una fecha y descuenta:
  - las fechas bloqueadas (`blocked_dates`),
  - el aviso mínimo (`min_notice_hours`),
  - las reservas vigentes (estados pending/accepted) que ya ocupan el cupo.

Todo se calcula en la ZONA HORARIA del servicio (IANA) y se compara contra
`now` en UTC, de modo que el «próximo turno libre» y el plazo de aviso sean
coherentes para empresa y cliente sin importar el huso del navegador.
"""
from __future__ import annotations

from datetime import datetime, timedelta, date, time, timezone
from zoneinfo import ZoneInfo
from typing import Any, Optional

from db_client import db

ACTIVE_BOOKING_STATES = ("pending", "accepted")
DEFAULT_HORIZON_DAYS = 45


def service_tz(service: dict) -> ZoneInfo:
    try:
        return ZoneInfo(service.get("timezone") or "America/Havana")
    except Exception:  # noqa: BLE001
        return ZoneInfo("America/Havana")


def _parse_hhmm(s: str) -> time:
    h, m = str(s).split(":")
    return time(int(h), int(m))


def slot_start_utc(service: dict, date_str: str, start_hhmm: str) -> datetime:
    tz = service_tz(service)
    d = date.fromisoformat(date_str)
    t = _parse_hhmm(start_hhmm)
    local = datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=tz)
    return local.astimezone(timezone.utc)


def slot_end_utc(service: dict, date_str: str, start_hhmm: str) -> datetime:
    dur = int(service.get("duration_minutes") or 0) or 60
    return slot_start_utc(service, date_str, start_hhmm) + timedelta(minutes=dur)


def day_candidates(service: dict, d: date) -> list[dict]:
    """Turnos candidatos de una fecha (sin filtrar por reservas ni aviso)."""
    windows = [w for w in (service.get("availability") or [])
               if int(w.get("day", -1)) == d.weekday()]
    dur = int(service.get("duration_minutes") or 0)
    buf = int(service.get("buffer_minutes") or 0)
    out: list[dict] = []
    for w in windows:
        try:
            ws = _parse_hhmm(w.get("start", "09:00"))
            we = _parse_hhmm(w.get("end", "17:00"))
        except Exception:  # noqa: BLE001
            continue
        start_dt = datetime.combine(d, ws)
        end_limit = datetime.combine(d, we)
        if dur <= 0:
            # Servicio sin duración fija (p. ej. presupuesto): un turno por
            # ventana en la hora de apertura.
            out.append({"start": ws.strftime("%H:%M"), "end": we.strftime("%H:%M")})
            continue
        step = max(1, dur + buf)
        cur = start_dt
        while cur + timedelta(minutes=dur) <= end_limit:
            slot_end = cur + timedelta(minutes=dur)
            out.append({"start": cur.strftime("%H:%M"),
                        "end": slot_end.strftime("%H:%M")})
            cur = cur + timedelta(minutes=step)
    seen: set[str] = set()
    uniq: list[dict] = []
    for s in sorted(out, key=lambda x: x["start"]):
        if s["start"] in seen:
            continue
        seen.add(s["start"])
        uniq.append(s)
    return uniq


def _free_for_day(service: dict, date_str: str, now: datetime,
                  counts: dict) -> list[dict]:
    """Turnos libres de una fecha dado un mapa de conteos ya cargado."""
    if date_str in (service.get("blocked_dates") or []):
        return []
    try:
        d = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return []
    candidates = day_candidates(service, d)
    if not candidates:
        return []
    min_notice = int(service.get("min_notice_hours") or 0)
    capacity = int(service.get("capacity") or 1) or 1
    out: list[dict] = []
    for c in candidates:
        start_utc = slot_start_utc(service, date_str, c["start"])
        if (start_utc - now) < timedelta(hours=min_notice):
            continue
        booked = int(counts.get((date_str, c["start"]), 0))
        if booked >= capacity:
            continue
        out.append({"start": c["start"], "end": c["end"],
                    "remaining": capacity - booked})
    return out


async def _active_counts(service_id: str, date_from: str,
                         date_to: str) -> dict:
    counts: dict = {}
    cursor = db.service_bookings.find(
        {"service_id": service_id,
         "status": {"$in": list(ACTIVE_BOOKING_STATES)},
         "slot_date": {"$gte": date_from, "$lte": date_to}},
        {"_id": 0, "slot_date": 1, "slot_start": 1})
    async for b in cursor:
        key = (b.get("slot_date"), b.get("slot_start"))
        counts[key] = counts.get(key, 0) + 1
    return counts


async def free_slots_for_date(service: dict, date_str: str, *,
                              now: Optional[datetime] = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    counts = await _active_counts(service["id"], date_str, date_str)
    return _free_for_day(service, date_str, now, counts)


async def next_free_slot(service: dict, *,
                         horizon_days: int = DEFAULT_HORIZON_DAYS,
                         now: Optional[datetime] = None) -> Optional[dict]:
    """Primer turno libre dentro del horizonte, o None si no hay horario."""
    if not (service.get("availability") or []):
        return None
    now = now or datetime.now(timezone.utc)
    tz = service_tz(service)
    today_local = now.astimezone(tz).date()
    last_local = today_local + timedelta(days=horizon_days)
    counts = await _active_counts(service["id"], today_local.isoformat(),
                                  last_local.isoformat())
    for i in range(horizon_days + 1):
        d = today_local + timedelta(days=i)
        slots = _free_for_day(service, d.isoformat(), now, counts)
        if slots:
            return {"date": d.isoformat(), "start": slots[0]["start"],
                    "end": slots[0]["end"]}
    return None
