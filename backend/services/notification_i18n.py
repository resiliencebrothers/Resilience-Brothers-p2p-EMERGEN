"""Backend notification i18n — iter74.

Central catalogue for every in-app notification title/message and every
Web-Push payload title/body the platform generates. Each callsite passes a
recipient language code (typically `user["preferred_language"]`) and gets
back the localised strings.

Design:
  - Single flat dict `CATALOG[key][lang]` returning `{title, message}` /
    `{title, body}` templates.
  - `.format(**params)` renders the templates. Callers pass numbers as-is;
    formatters like `:g` are baked into the template strings themselves.
  - `resolve_lang(user_id)` fetches `preferred_language` in one query and
    falls back to Spanish (the platform's original default). Every caller
    should prefer passing the full user dict when it has it (saves a
    round-trip); when it doesn't, it can call `resolve_lang` directly.
  - The dictionary key set mirrors the notification `type` field stored in
    Mongo, so filtering / regex-searching stays consistent.

Only two languages are supported today (`es`, `en`) matching the frontend
`i18next` locales. Adding a third language is a pure-data change here.
"""
from __future__ import annotations
from typing import Any, Optional


DEFAULT_LANG = "es"
SUPPORTED = {"es", "en"}


def _norm(lang: Optional[str]) -> str:
    """Coerce a raw locale string to one of `SUPPORTED`.
    Accepts 'en', 'EN', 'en-US', 'en_gb' → 'en'. Anything else → default."""
    if not lang:
        return DEFAULT_LANG
    head = lang.strip().lower().split("-")[0].split("_")[0]
    return head if head in SUPPORTED else DEFAULT_LANG


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

# NOTE ON FORMATTING:
# - `{name}`, `{email}`, `{phone}` etc. are `.format()` placeholders.
# - Number formatters like `{rate:g}` are honoured — pass the raw number.
# - Trailing punctuation is part of the template so we don't accumulate
#   whitespace/period issues between locales.

CATALOG: dict[str, dict[str, dict[str, str]]] = {
    # -----------------------------------------------------------------------
    # STAFF FANOUT
    # -----------------------------------------------------------------------
    "new_user_pending": {
        "es": {
            "title": "Nuevo usuario pendiente de verificación",
            "message": "{name} ({email}) acaba de registrarse con el teléfono {phone}. Verifica o rechaza desde Admin → Usuarios.",
            "push_body": "{name} ({phone}). Verifica o rechaza desde Admin → Usuarios.",
        },
        "en": {
            "title": "New user awaiting verification",
            "message": "{name} ({email}) just signed up with phone {phone}. Approve or reject from Admin → Users.",
            "push_body": "{name} ({phone}). Approve or reject from Admin → Users.",
        },
    },
    "new_appeal": {
        "es": {
            "title": "Nueva apelación de cliente",
            "message": "{name} ({email}) envió una apelación para reactivar su cuenta bajo revisión. Ábrela en Admin → Apelaciones.",
        },
        "en": {
            "title": "New client appeal",
            "message": "{name} ({email}) submitted an appeal to reactivate their under-review account. Open it in Admin → Appeals.",
        },
    },
    # -----------------------------------------------------------------------
    # CLIENT — PHONE VERIFICATION
    # -----------------------------------------------------------------------
    "phone_verified": {
        "es": {
            "title": "¡Tu cuenta está activa!",
            "message": "Hemos verificado tu teléfono. Ya puedes operar en la plataforma: hacer intercambios, retiros y canjes.",
            "push_title": "¡Tu cuenta está activa! ✓",
            "push_body": "Hemos verificado tu teléfono. Ya puedes operar en la plataforma.",
        },
        "en": {
            "title": "Your account is active!",
            "message": "We verified your phone. You can now trade on the platform: exchanges, withdrawals and redemptions.",
            "push_title": "Your account is active! ✓",
            "push_body": "We verified your phone. You can now trade on the platform.",
        },
    },
    "phone_rejected": {
        "es": {
            "title": "Verificación rechazada",
            "message": "No pudimos verificar tu teléfono. Motivo: {reason}. Si crees que es un error, contacta a soporte por WhatsApp para apelar.",
            "push_body_fallback": "Tu teléfono no pudo ser verificado. Contacta a soporte.",
        },
        "en": {
            "title": "Verification rejected",
            "message": "We could not verify your phone. Reason: {reason}. If you believe this is an error, contact support on WhatsApp to appeal.",
            "push_body_fallback": "We could not verify your phone. Please contact support.",
        },
    },
    # -----------------------------------------------------------------------
    # CLIENT — APPEAL REVIEW
    # -----------------------------------------------------------------------
    "appeal_resolved": {
        "es": {
            "title": "Apelación aprobada",
            "message": "El staff revisó tu apelación y la aprobó. Mensaje del equipo: {response}. Si la cuenta sigue bajo revisión, un admin la activará en las próximas horas.",
        },
        "en": {
            "title": "Appeal approved",
            "message": "Staff reviewed your appeal and approved it. Team message: {response}. If the account is still under review, an admin will activate it within the next few hours.",
        },
    },
    "appeal_rejected": {
        "es": {
            "title": "Apelación rechazada",
            "message": "El staff revisó tu apelación pero no procedió. Mensaje del equipo: {response}. Puedes contactar a soporte por WhatsApp si necesitas otra vía.",
        },
        "en": {
            "title": "Appeal rejected",
            "message": "Staff reviewed your appeal but did not proceed. Team message: {response}. You can reach out to support on WhatsApp if you need another route.",
        },
    },
    # -----------------------------------------------------------------------
    # CLIENT — KYC
    # -----------------------------------------------------------------------
    "kyc_verified": {
        "es": {
            "title": "Identidad verificada ✓",
            "message": "Tu documento y selfie fueron aprobados. Ya operas con identidad verificada; los límites transaccionales se ajustaron a tu nivel.",
        },
        "en": {
            "title": "Identity verified ✓",
            "message": "Your document and selfie were approved. You now trade with a verified identity; transactional limits were adjusted to your tier.",
        },
    },
    "kyc_rejected": {
        "es": {
            "title": "Verificación rechazada",
            "message": "No pudimos aprobar tu verificación de identidad. Motivo: {reason_txt}.{tail} Puedes subir nuevos documentos desde el menú de tu cuenta.",
            "reason_default": "Documentación insuficiente",
            "tail_prefix": " Nota del equipo: ",
        },
        "en": {
            "title": "Verification rejected",
            "message": "We could not approve your identity verification. Reason: {reason_txt}.{tail} You can upload new documents from your account menu.",
            "reason_default": "Insufficient documentation",
            "tail_prefix": " Team note: ",
        },
    },
    "kyc_needs_more_info": {
        "es": {
            "title": "Necesitamos más información",
            "message": "Tu verificación está pausada. {notes} Actualiza tus documentos y vuelve a enviar desde tu perfil.",
        },
        "en": {
            "title": "We need more information",
            "message": "Your verification is on hold. {notes} Update your documents and resubmit from your profile.",
        },
    },
    # -----------------------------------------------------------------------
    # CLIENT — ORDER STATUS (mirrored from `services/orders_helpers.py`)
    # -----------------------------------------------------------------------
    "order_approved": {
        "es": {
            "title": "Orden #{short_id} confirmada",
            "message": "Recibimos tu pago. Estamos preparando la entrega de {amt} {code}.",
            "push_title": "Orden #{short_id} aprobada ✓",
            "push_body": "{amt} {code} listos para entregar.",
        },
        "en": {
            "title": "Order #{short_id} confirmed",
            "message": "We received your payment. We're preparing the delivery of {amt} {code}.",
            "push_title": "Order #{short_id} approved ✓",
            "push_body": "{amt} {code} ready for delivery.",
        },
    },
    "order_rejected": {
        "es": {
            "title": "Orden #{short_id} rechazada",
            "message_note": "{note}",
            "message_default": "Por favor revisa los detalles en tu dashboard.",
            "push_title": "Orden #{short_id} rechazada",
            "push_body_default": "Por favor revisa los detalles desde tu dashboard.",
        },
        "en": {
            "title": "Order #{short_id} rejected",
            "message_note": "{note}",
            "message_default": "Please review the details in your dashboard.",
            "push_title": "Order #{short_id} rejected",
            "push_body_default": "Please review the details in your dashboard.",
        },
    },
    "order_completed": {
        "es": {
            "title": "Orden #{short_id} completada",
            "msg_accumulate": "Se acreditaron {amt} {code} a tu saldo VIP.",
            "msg_crypto": "Enviamos {amt} {code} a tu wallet. Revisa el TX hash en la orden.",
            "msg_crypto_with_net": "Enviamos {amt} {code} a tu wallet. Verifica la transacción en {network}.",
            "msg_cash": "Efectivo de {amt} {code} entregado. Confirma la recepción.",
            "msg_transfer": "Transferimos {amt} {code} a tu cuenta. Revisa el comprobante.",
            "push_title": "Orden #{short_id} completada ✓",
            "push_accumulate": "Se acreditó {amt} {code} a tu saldo VIP.",
            "push_crypto": "Enviamos {amt} {code} a tu wallet. Revisa el TX hash.",
            "push_cash": "Efectivo de {amt} {code} entregado. Confirma la recepción.",
            "push_transfer": "Transferimos {amt} {code} a tu cuenta. Revisa el comprobante.",
        },
        "en": {
            "title": "Order #{short_id} completed",
            "msg_accumulate": "{amt} {code} credited to your VIP balance.",
            "msg_crypto": "We sent {amt} {code} to your wallet. Check the TX hash on the order.",
            "msg_crypto_with_net": "We sent {amt} {code} to your wallet. Verify the transaction on {network}.",
            "msg_cash": "Cash payout of {amt} {code} delivered. Please confirm receipt.",
            "msg_transfer": "We transferred {amt} {code} to your account. Check the receipt.",
            "push_title": "Order #{short_id} completed ✓",
            "push_accumulate": "{amt} {code} credited to your VIP balance.",
            "push_crypto": "We sent {amt} {code} to your wallet. Check the TX hash.",
            "push_cash": "Cash payout of {amt} {code} delivered. Please confirm receipt.",
            "push_transfer": "We transferred {amt} {code} to your account. Check the receipt.",
        },
    },
    # -----------------------------------------------------------------------
    # CLIENT — RATE CHANGE FANOUT (from `routes/market.py`)
    # -----------------------------------------------------------------------
    "rate_change": {
        "es": {
            "title": "Nueva tasa {from_code} → {to_code}",
            "message": "1 {from_code} = {rate:g} {to_code}{vip_suffix}.",
            "vip_suffix": " (tarifa VIP)",
            "push_body": "1 {from_code} = {rate:g} {to_code}{vip_suffix}. Revisa el dashboard antes de intercambiar.",
            "push_vip_suffix": " (VIP)",
        },
        "en": {
            "title": "New rate {from_code} → {to_code}",
            "message": "1 {from_code} = {rate:g} {to_code}{vip_suffix}.",
            "vip_suffix": " (VIP rate)",
            "push_body": "1 {from_code} = {rate:g} {to_code}{vip_suffix}. Check the dashboard before trading.",
            "push_vip_suffix": " (VIP)",
        },
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def t(key: str, lang: Optional[str], field: str, **params: Any) -> str:
    """Return the localised template `CATALOG[key][lang][field]` rendered
    against `**params`. If the language is unknown or the field is missing,
    falls back to Spanish. If Spanish is also missing (developer error) the
    key string itself is returned as a last-resort surface so runtime never
    crashes on a notification lookup."""
    normalised = _norm(lang)
    section = CATALOG.get(key)
    if not section:
        return key
    entry = section.get(normalised) or section.get(DEFAULT_LANG)
    if not entry:
        return key
    template = entry.get(field)
    if template is None and normalised != DEFAULT_LANG:
        template = section.get(DEFAULT_LANG, {}).get(field)
    if template is None:
        return key
    try:
        return template.format(**params)
    except (KeyError, IndexError) as e:
        # A missing placeholder is a bug — surface the key so it's easy to
        # find in logs but never crash the caller.
        import logging
        logging.getLogger(__name__).error(
            f"i18n render failed for key={key} field={field} lang={normalised}: {e}"
        )
        return template  # unrendered template so callers still get *something*


async def resolve_lang(db, user_id: str) -> str:
    """Look up the recipient's preferred_language from Mongo. Returns 'es'
    as the safe default when the user is unknown or the field is missing."""
    if not user_id:
        return DEFAULT_LANG
    doc = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "preferred_language": 1},
    )
    if not doc:
        return DEFAULT_LANG
    return _norm(doc.get("preferred_language"))


def get_field(key: str, lang: Optional[str], field: str, default: str = "") -> str:
    """Return the raw catalogue string `CATALOG[key][lang][field]` (no
    `.format()` applied). Useful for callers that need the untemplated
    fragment (e.g. per-locale connector words). Falls back to Spanish, then
    to `default` if neither locale defines the field."""
    normalised = _norm(lang)
    section = CATALOG.get(key, {})
    entry = section.get(normalised) or section.get(DEFAULT_LANG) or {}
    if field in entry:
        return entry[field]
    fallback = section.get(DEFAULT_LANG, {})
    return fallback.get(field, default)
