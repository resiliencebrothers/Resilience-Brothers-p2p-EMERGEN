"""Saved crypto withdrawal addresses — iter184.

- GET    /vip/crypto-addresses          → user's saved list
- POST   /vip/crypto-addresses          → save {label, address, network}
- DELETE /vip/crypto-addresses/{aid}
"""
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db_client import db
from auth_utils import require_user, now_utc, iso
from services.crypto_networks import (
    SUPPORTED_NETWORKS, is_supported_network,
    is_address_valid_for_network, mismatch_reason,
)

router = APIRouter(tags=["CryptoAddresses"])

MAX_SAVED = 50


class SavedAddressCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=60)
    address: str = Field(..., min_length=10, max_length=120)
    network: str


@router.get("/vip/crypto-addresses")
async def list_addresses(request: Request) -> Any:
    user = await require_user(request)
    items = await db.crypto_addresses.find(
        {"user_id": user["user_id"]}, {"_id": 0},
    ).sort("created_at", -1).to_list(MAX_SAVED)
    return {"items": items}


@router.post("/vip/crypto-addresses")
async def save_address(payload: SavedAddressCreate, request: Request) -> Any:
    user = await require_user(request)
    network = (payload.network or "").strip().upper()
    if not is_supported_network(network):
        raise HTTPException(
            status_code=400,
            detail=f"Red no soportada. Redes válidas: {', '.join(SUPPORTED_NETWORKS)}.",
        )
    address = payload.address.strip()
    if not is_address_valid_for_network(address, network):
        raise HTTPException(status_code=400, detail=mismatch_reason(address, network))
    dup = await db.crypto_addresses.find_one(
        {"user_id": user["user_id"], "address": address, "network": network})
    if dup:
        raise HTTPException(status_code=409, detail="Esta dirección ya está guardada.")
    count = await db.crypto_addresses.count_documents({"user_id": user["user_id"]})
    if count >= MAX_SAVED:
        raise HTTPException(
            status_code=400,
            detail=f"Límite de {MAX_SAVED} direcciones guardadas alcanzado.",
        )
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["user_id"],
        "label": payload.label.strip(),
        "address": address,
        "network": network,
        "created_at": iso(now_utc()),
    }
    await db.crypto_addresses.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/vip/crypto-addresses/{aid}")
async def delete_address(aid: str, request: Request) -> Any:
    user = await require_user(request)
    r = await db.crypto_addresses.delete_one({"id": aid, "user_id": user["user_id"]})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Dirección no encontrada")
    return {"ok": True}
