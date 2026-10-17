"""TOOLS-02 — escenarios de rentabilidad guardados, PRIVADOS por cuenta.

Cada usuario (VIP/Empresa) guarda, renombra, carga y borra sus propios
cálculos favoritos de la calculadora de rentabilidad. Un escenario almacena un
nombre + el estado `calc` de la calculadora (inputs). Sin lógica financiera en
backend: es solo persistencia del formulario del cliente.
"""
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db_client import db
from auth_utils import require_user, iso, now_utc

router = APIRouter(tags=["ProfitScenarios"])

MAX_PER_USER = 50


class ScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    calc: Dict[str, Any] = Field(default_factory=dict)


class ScenarioUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    calc: Optional[Dict[str, Any]] = None


def _public(doc: dict) -> dict:
    return {
        "id": doc["id"], "name": doc["name"], "calc": doc.get("calc") or {},
        "created_at": doc.get("created_at"), "updated_at": doc.get("updated_at"),
    }


@router.get("/profit/scenarios")
async def list_scenarios(request: Request) -> Any:
    user = await require_user(request)
    docs = await db.profit_scenarios.find(
        {"owner_id": user["user_id"]}, {"_id": 0}).sort("updated_at", -1).to_list(200)
    return [_public(d) for d in docs]


@router.post("/profit/scenarios")
async def create_scenario(payload: ScenarioCreate, request: Request) -> Any:
    user = await require_user(request)
    count = await db.profit_scenarios.count_documents({"owner_id": user["user_id"]})
    if count >= MAX_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=f"Máximo {MAX_PER_USER} escenarios guardados")
    now = iso(now_utc())
    doc = {
        "id": f"psc_{uuid.uuid4().hex[:12]}",
        "owner_id": user["user_id"],
        "name": payload.name.strip(),
        "calc": payload.calc,
        "created_at": now,
        "updated_at": now,
    }
    await db.profit_scenarios.insert_one({**doc})
    return _public(doc)


@router.put("/profit/scenarios/{scenario_id}")
async def update_scenario(scenario_id: str, payload: ScenarioUpdate,
                          request: Request) -> Any:
    user = await require_user(request)
    doc = await db.profit_scenarios.find_one(
        {"id": scenario_id, "owner_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Escenario no encontrado")
    upd: dict = {"updated_at": iso(now_utc())}
    if payload.name is not None:
        upd["name"] = payload.name.strip()
    if payload.calc is not None:
        upd["calc"] = payload.calc
    await db.profit_scenarios.update_one({"id": scenario_id}, {"$set": upd})
    fresh = await db.profit_scenarios.find_one({"id": scenario_id}, {"_id": 0})
    return _public(fresh)


@router.delete("/profit/scenarios/{scenario_id}")
async def delete_scenario(scenario_id: str, request: Request) -> Any:
    user = await require_user(request)
    res = await db.profit_scenarios.delete_one(
        {"id": scenario_id, "owner_id": user["user_id"]})
    if res.deleted_count != 1:
        raise HTTPException(status_code=404, detail="Escenario no encontrado")
    return {"ok": True}
