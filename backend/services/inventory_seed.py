"""iter219 — Carga inicial del inventario desde el Excel del operador
(`Inventario_flujo_caja_CORREGIDO`): 30 productos del mercadito con su
cantidad inicial, costo unitario y precio real de venta.

Se ejecuta en el startup del backend de forma idempotente (marker en
settings.global.excel_inventory_seeded_at + dedup por nombre), así también
corre solo en producción tras el redeploy.

Los productos entran como inventario de la EMPRESA activos en el marketplace
(el operador puede ocultarlos con el toggle de publicación).
"""
import logging

from db_client import db
from auth_utils import now_utc, iso
from routes.market import Product

logger = logging.getLogger(__name__)

# (nombre, cant. unidades, costo unitario, precio real mercadito)
EXCEL_CATALOG = [
    ("Maicena", 40, 330.0, 390.0),
    ("Leche condensada", 48, 780.0, 850.0),
    ("Pan Rallado", 24, 900.0, 1000.0),
    ("Detergente líquido 1L s/etiq.", 12, 700.0, 750.0),
    ("Arroz Guyanes 1kg", 24, 680.3, 800.0),
    ("Papel Sanitario", 80, 510.0, 600.0),
    ("Cerveza La Fría", 120, 435.0, 520.0),
    ("Cerveza Unlaguer", 120, 410.0, 450.0),
    ("Refresco Mate lata", 72, 400.0, 480.0),
    ("Refresco Cola lata", 120, 380.0, 450.0),
    ("Malta Guajira", 10, 440.0, 500.0),
    ("Galletas Crakeñas", 36, 1220.0, 1300.0),
    ("Toallitas Húmedas", 20, 540.0, 600.0),
    ("Gelatina", 96, 200.0, 280.0),
    ("Sorbeto Baducco", 36, 290.0, 320.0),
    ("Café Morro", 24, 2500.0, 2800.0),
    ("Galletas María", 24, 510.0, 600.0),
    ("Agua pequeña", 24, 200.0, 240.0),
    ("Cerveza Royal Duque", 72, 365.0, 400.0),
    ("Refresco Limón lata", 48, 370.0, 450.0),
    ("Malta Bucanero", 120, 500.0, 600.0),
    ("Harina de Trigo 50kg", 100, 390.0, 450.0),
    ("Sal fina 50kg", 200, 140.0, 200.0),
    ("Café Nezca", 10, 2100.0, 2650.0),
    ("Detergente líquido 1L c/etiq.", 12, 490.0, 800.0),
    ("Jugo de mango Nezka", 24, 495.83, 550.0),
    ("Ketchup Pramesa", 24, 670.83, 800.0),
    ("Spaguetti 500g", 80, 300.0, 350.0),
    ("Leche evaporada", 30, 750.0, 850.0),
    ("Detergente 500g", 28, 690.0, 800.0),
]

SEED_CATEGORY = "mercadito"

_IMG_BASE = "https://static.prod-images.emergentagent.com/jobs/5194ffe2-e544-4a34-b4ab-904136df5054/images"

# iter224 — fotos de producto generadas para el catálogo del Excel.
EXCEL_PHOTOS = {
    "Maicena": f"{_IMG_BASE}/f71516b9ae3de5f2ff69987ba13490ef7b332ef3e8a774b71ab4fa035fa81567.jpeg",
    "Leche condensada": f"{_IMG_BASE}/fa6db6a23c76c711cae251fb779caf32defb0e763a854f3f59e7b33cb548bcdd.jpeg",
    "Pan Rallado": f"{_IMG_BASE}/bd457d48ecb9d5aadb0422b693a68a406222aec1c4e9172b0263797f5339b559.jpeg",
    "Detergente líquido 1L s/etiq.": f"{_IMG_BASE}/3511c5837a2acbb20e0ef9d67217d5d9e937d83f35f4797a6cf3423ab7564892.jpeg",
    "Arroz Guyanes 1kg": f"{_IMG_BASE}/8db7e3ade10786a6c499b78067b303d2592a18842fa3e1a88f55d6b3e2962c8d.jpeg",
    "Papel Sanitario": f"{_IMG_BASE}/952bd5722fe4d352d78f8da19f65c24aa3637ed9320227c8e41d5347a02fadb4.jpeg",
    "Cerveza La Fría": f"{_IMG_BASE}/73c59196b983cf34b2b6c061da5a3a497510c35d484ac591cb7c253c38b4d6f7.jpeg",
    "Cerveza Unlaguer": f"{_IMG_BASE}/396828a68879f47e5ebfdf3d0a4d735fb1deb7081b5de262bcfa9e7fb2df4180.jpeg",
    "Refresco Mate lata": f"{_IMG_BASE}/ae6ff5984146233f7293ad8a6e2331ba210be59c5fe3258747d061c57ebdd0f6.jpeg",
    "Refresco Cola lata": f"{_IMG_BASE}/f3eaed57a0d50e268bef40c96c9a086e07746918b655418dafc2dcfc53a99e20.jpeg",
    "Malta Guajira": f"{_IMG_BASE}/65c3368f1379c36d357fec4f4999ec2850f815e1020947d8d8108de3c1f30627.jpeg",
    "Galletas Crakeñas": f"{_IMG_BASE}/b228e9656fcb556145351a852ba5bc2c84981d3e9dcd644d9aabc799281e9eac.jpeg",
    "Toallitas Húmedas": f"{_IMG_BASE}/37c16a70456b911c27ee431cd1093a4330d0bf3de2e35a68de00cadeff794080.jpeg",
    "Gelatina": f"{_IMG_BASE}/d458a8768b4338ef51339ca5741b8c5bcea09037e0a60943b68264a94fe45f58.jpeg",
    "Sorbeto Baducco": f"{_IMG_BASE}/a0defd9100b52888aa3fb48523c9702f4bc5c47507187ed464f68eb9e00c238e.jpeg",
    "Café Morro": f"{_IMG_BASE}/b5283a162bc208b98e49840c04ad4ea8e168db7012d9fcbc0f1fb2abf0b57804.jpeg",
    "Galletas María": f"{_IMG_BASE}/28cadf810bff81a51d9a1d30038077ab1fc9954c5829d25165b5c1fefc6a2b5e.jpeg",
    "Agua pequeña": f"{_IMG_BASE}/627c51fbbf45c8c450c001cf736e2ef0f57c0395423d908b7b01502b3faaeb42.jpeg",
    "Cerveza Royal Duque": f"{_IMG_BASE}/eeadedb49bf42d06d9d3409729170176ea68992a127be85f9e96505defa6d877.jpeg",
    "Refresco Limón lata": f"{_IMG_BASE}/3110332ee666260782f3ced4209938d9f6ad0d83b1d6b39729bb9c0929da22c2.jpeg",
    "Malta Bucanero": f"{_IMG_BASE}/8a7b704f3761c3fb04301d2b8fb76f68012830e194302c9fcf3d435acdbce97e.jpeg",
    "Harina de Trigo 50kg": f"{_IMG_BASE}/b9fb8437e74671cc4dbd092d3f22efbbc13f37bcd17df1c5f9f4ed7056bfd2b4.jpeg",
    "Sal fina 50kg": f"{_IMG_BASE}/472279a387d654926c0879602bf5f52c39759f672d1126871bb02ec9473183d8.jpeg",
    "Café Nezca": f"{_IMG_BASE}/87c77df8f67d9fac7ad56f45ce2093db46d2a311dc460158d539dc21a0422ea4.jpeg",
    "Detergente líquido 1L c/etiq.": f"{_IMG_BASE}/93a6344ce632aee8a568925d677098931b346caded3dc0e8393eb09d75020e38.jpeg",
    "Jugo de mango Nezka": f"{_IMG_BASE}/5deaf2653bc43e64426aaa73ddb86f0f923d299c7ed46c10e078329dbd477a5a.jpeg",
    "Ketchup Pramesa": f"{_IMG_BASE}/a19fea1ac998116babca081a0cf14aed74eb261d40686dd36046af748c328b89.jpeg",
    "Spaguetti 500g": f"{_IMG_BASE}/8a6187ffe6805eeb214c539e0ede802be5705fb2e56b9a806c6e3a57989c66ed.jpeg",
    "Leche evaporada": f"{_IMG_BASE}/10e6e088f2d9f7a89dec0896e2c5dee241aa3dfc636831fc28fa12a445900088.jpeg",
    "Detergente 500g": f"{_IMG_BASE}/1debcfeda60ceeb46720437c190f3d14e082f07d1566108f2701810ad04823d9.jpeg",
}


async def apply_excel_product_photos_once() -> int:
    """iter224 — migración única: asigna las fotos generadas a los productos
    del Excel que aún no tengan imagen (no pisa fotos subidas a mano)."""
    marker = await db.settings.find_one(
        {"id": "global"}, {"_id": 0, "excel_inventory_photos_at": 1}) or {}
    if marker.get("excel_inventory_photos_at"):
        return 0
    applied = 0
    for name, url in EXCEL_PHOTOS.items():
        res = await db.products.update_many(
            {"name": {"$regex": f"^{name}$", "$options": "i"},
             "$or": [{"image_url": {"$in": [None, ""]}},
                     {"image_url": {"$exists": False}}]},
            {"$set": {"image_url": url}})
        applied += res.modified_count
    await db.settings.update_one(
        {"id": "global"},
        {"$set": {"id": "global",
                  "excel_inventory_photos_at": iso(now_utc())}},
        upsert=True)
    logger.info(f"[inventory-seed] {applied} fotos de producto aplicadas")
    return applied


async def seed_excel_inventory() -> int:
    """Inserta los productos del Excel que aún no existan. Devuelve cuántos creó."""
    marker = await db.settings.find_one(
        {"id": "global"}, {"_id": 0, "excel_inventory_seeded_at": 1}) or {}
    if marker.get("excel_inventory_seeded_at"):
        return 0
    created = 0
    for name, qty, cost, price in EXCEL_CATALOG:
        exists = await db.products.find_one(
            {"name": {"$regex": f"^{name}$", "$options": "i"}}, {"id": 1})
        if exists:
            continue
            # iter223 — activos por defecto para que aparezcan en el marketplace.
        p = Product(
            name=name,
            description="Inventario inicial importado del Excel del mercadito",
            price_usd=price,
            cost_usd=cost,
            stock=int(qty),
            category=SEED_CATEGORY,
            is_active=True,
        )
        await db.products.insert_one(p.model_dump())
        created += 1
    await db.settings.update_one(
        {"id": "global"},
        {"$set": {"id": "global", "excel_inventory_seeded_at": iso(now_utc())}},
        upsert=True)
    logger.info(f"[inventory-seed] {created} productos del Excel importados")
    return created


async def activate_excel_inventory_once() -> int:
    """iter223 — migración única: el operador quiere los productos del Excel
    visibles en el marketplace (nacieron ocultos). Corre una sola vez por
    entorno (marker excel_inventory_activated_at)."""
    marker = await db.settings.find_one(
        {"id": "global"}, {"_id": 0, "excel_inventory_activated_at": 1}) or {}
    if marker.get("excel_inventory_activated_at"):
        return 0
    res = await db.products.update_many(
        {"category": SEED_CATEGORY, "is_active": False},
        {"$set": {"is_active": True}})
    await db.settings.update_one(
        {"id": "global"},
        {"$set": {"id": "global",
                  "excel_inventory_activated_at": iso(now_utc())}},
        upsert=True)
    logger.info(f"[inventory-seed] {res.modified_count} productos del Excel publicados")
    return res.modified_count
