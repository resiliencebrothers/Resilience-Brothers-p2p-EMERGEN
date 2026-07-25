"""iter102 — FAQ seed for `/dashboard/support`.

Idempotent: only inserts entries that don't already exist. Admins can
edit / delete / add entries from `/admin/support/faq` without touching
this file. Editing this file is only useful for shipping a *baseline*
FAQ to new environments (staging / production first-boot).

Every entry carries both ES and EN copy so the client-side language
switcher works without extra network hops.
"""
from datetime import datetime, timezone
from typing import Any
import logging
import uuid

logger = logging.getLogger(__name__)


DEFAULT_FAQ = [
    # ── CUENTA ────────────────────────────────────────────────────────
    {
        "category": "general",
        "order": 10,
        "question_es": "¿Cómo creo mi cuenta?",
        "question_en": "How do I create my account?",
        "answer_es": "Haz clic en 'Iniciar sesión' → 'Continuar con Google' o "
                     "'Registrarse con email' desde la landing. Después registra tu "
                     "teléfono con código país (ej. +34, +52, +54) y espera que el "
                     "staff verifique tu identidad. Recibirás una notificación "
                     "cuando tu cuenta esté activa.",
        "answer_en": "Click 'Sign in' → 'Continue with Google' or 'Sign up with email' "
                     "from the landing page. Then register your phone with country "
                     "code (e.g. +34, +52, +54) and wait for staff to verify your "
                     "identity. You'll be notified when your account is active.",
    },
    # ── KYC ───────────────────────────────────────────────────────────
    {
        "category": "kyc",
        "order": 20,
        "question_es": "¿Por qué necesito hacer KYC?",
        "question_en": "Why do I need to complete KYC?",
        "answer_es": "El KYC (Know Your Customer) es un requisito regulatorio "
                     "para prevenir lavado de dinero y proteger a todos los usuarios. "
                     "Sin KYC aprobado no puedes operar montos grandes ni retirar a "
                     "cuentas bancarias externas. El proceso toma menos de 5 minutos "
                     "y solo necesitas un documento de identidad y una foto tuya.",
        "answer_en": "KYC (Know Your Customer) is a regulatory requirement to "
                     "prevent money laundering and protect all users. Without an "
                     "approved KYC you can't operate large amounts or withdraw to "
                     "external bank accounts. The process takes less than 5 minutes "
                     "and only requires an ID document and a selfie.",
    },
    {
        "category": "kyc",
        "order": 30,
        "question_es": "¿Cuánto tarda la aprobación del KYC?",
        "question_en": "How long does KYC approval take?",
        "answer_es": "Normalmente entre 1 y 4 horas en horario hábil (10:00–20:00 GMT). "
                     "Si tu KYC está pendiente más de 24h abre un ticket de soporte y "
                     "revisaremos manualmente.",
        "answer_en": "Usually between 1 and 4 hours during business hours (10:00–20:00 "
                     "GMT). If your KYC is pending for more than 24h open a support "
                     "ticket and we'll review it manually.",
    },
    # ── CONVERSIONES ──────────────────────────────────────────────────
    {
        "category": "convert",
        "order": 40,
        "question_es": "¿Qué es la conversión instantánea entre saldos?",
        "question_en": "What is instant self-conversion between balances?",
        "answer_es": "Si tienes saldo en varias monedas dentro de la plataforma "
                     "(por ejemplo USD y USDT), puedes convertir de una a otra "
                     "al instante desde tu dashboard sin abrir una orden P2P. "
                     "La tasa aplicada es la del mercado real menos una pequeña "
                     "comisión (0.01 USDT).",
        "answer_en": "If you hold balance in multiple currencies (e.g. USD and "
                     "USDT), you can convert between them instantly from your "
                     "dashboard without opening a P2P order. The rate applied is "
                     "the real market rate minus a small fee (0.01 USDT).",
    },
    {
        "category": "convert",
        "order": 45,
        "question_es": "¿Por qué la conversión da un monto menor al esperado?",
        "question_en": "Why does the conversion return less than expected?",
        "answer_es": "La plataforma aplica su tasa real de mercado. Por ejemplo, "
                     "si conviertes 100 USD → USDT y la tasa USDT/USD es 1.05, "
                     "recibes ~95.24 USDT (100 ÷ 1.05). Los clientes VIP obtienen "
                     "un margen más favorable. La tasa exacta se muestra en el modal "
                     "antes de confirmar.",
        "answer_en": "The platform applies its real market rate. E.g., converting "
                     "100 USD → USDT with a USDT/USD rate of 1.05 gives you ~95.24 "
                     "USDT (100 ÷ 1.05). VIP clients get a better spread. The exact "
                     "rate is shown in the modal before you confirm.",
    },
    # ── RETIROS ───────────────────────────────────────────────────────
    {
        "category": "withdrawal",
        "order": 50,
        "question_es": "¿Cómo retiro dinero de mi saldo?",
        "question_en": "How do I withdraw money from my balance?",
        "answer_es": "Ve a Dashboard → VIP → Retirar. Escoge el método (cripto, "
                     "transferencia bancaria, efectivo), completa los datos y "
                     "confirma con tu código 2FA. El staff procesa retiros en un "
                     "plazo máximo de 24h desde la solicitud.",
        "answer_en": "Go to Dashboard → VIP → Withdraw. Choose the method (crypto, "
                     "bank transfer, cash), fill in the details and confirm with "
                     "your 2FA code. Staff processes withdrawals within 24h max.",
    },
    # ── COMISIONES ────────────────────────────────────────────────────
    {
        "category": "fees",
        "order": 60,
        "question_es": "¿Qué comisiones cobra la plataforma?",
        "question_en": "What fees does the platform charge?",
        "answer_es": "Órdenes P2P: 0% de comisión para clientes VIP y 0.5% para "
                     "clientes normales. Conversiones instantáneas: 0.01 USDT por "
                     "operación. Retiros a cripto: variable según red (te avisamos "
                     "antes de confirmar). Transferencias internas entre balances "
                     "del mismo usuario: gratis.",
        "answer_en": "P2P orders: 0% fee for VIP clients and 0.5% for normal "
                     "clients. Instant conversions: 0.01 USDT per operation. "
                     "Crypto withdrawals: variable per network (shown before you "
                     "confirm). Internal transfers between your own balances: free.",
    },
    # ── CONTACTO ──────────────────────────────────────────────────────
    {
        "category": "other",
        "order": 90,
        "question_es": "¿Cómo contacto con soporte si mi problema no está aquí?",
        "question_en": "How do I contact support if my issue isn't listed here?",
        "answer_es": "Abre un ticket desde esta misma página con la categoría más "
                     "cercana a tu problema. El staff responde en menos de 24h y te "
                     "avisamos por notificación push cuando tengamos respuesta. Los "
                     "tickets marcados como 'urgente' (pérdida de saldo, cuenta "
                     "comprometida) se atienden con prioridad.",
        "answer_en": "Open a ticket on this same page with the category closest to "
                     "your issue. Staff replies within 24h and we'll ping you via "
                     "push notification when there's a response. Tickets tagged as "
                     "'urgent' (lost balance, compromised account) are prioritised.",
    },
]


async def seed_faq_defaults(db: Any) -> None:
    """Insert baseline FAQ entries if the collection is empty.

    NOT called on every startup — only wired via a `_faq_seed_done` sentinel
    document in the DB so a re-run is safe. Admins can then edit each entry
    from `/admin/support/faq` without collisions.
    """
    if await db.faq_entries.count_documents({}) > 0:
        return
    now = datetime.now(timezone.utc).isoformat()
    docs = []
    for entry in DEFAULT_FAQ:
        docs.append({
            "id": uuid.uuid4().hex,
            **entry,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        })
    await db.faq_entries.insert_many(docs)
    logger.info(f"[support] Seeded {len(docs)} FAQ entries.")
